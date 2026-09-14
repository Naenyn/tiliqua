/// Integer sine/cosine for the 5-degree camera steps, in Q8 format.
fn sin_cos_q8(angle: i8) -> (i32, i32) {
    // round(256 * sin(theta)) for theta = 0, 5, ... 90 degrees. Cosine is
    // the same quarter-wave table read in reverse. AngleParams constrains all
    // UI values to this grid; clamping also makes a damaged saved value safe.
    const SIN_Q8: [i32; 19] = [
        0, 22, 44, 66, 88, 108, 128, 147, 165, 181, 196, 210, 222, 232, 241, 247, 252, 255, 256,
    ];
    let index = core::cmp::min(angle.unsigned_abs() as usize / 5, SIN_Q8.len() - 1);
    let sin = SIN_Q8[index];
    let cos = SIN_Q8[SIN_Q8.len() - 1 - index];
    (if angle < 0 { -sin } else { sin }, cos)
}

fn mul_q8(a: i32, b: i32) -> i32 {
    let product = a * b;
    // Arithmetic right shift floors negative products. Round both signs to
    // the nearest Q8 value instead so rotations do not acquire a directional
    // bias from repeated matrix multiplies.
    let correction = if product < 0 { 127 } else { 128 };
    (product + correction) >> 8
}

/// Build two rows of an Euler-rotated orthographic camera matrix. The base
/// projection keeps frequency horizontal, amplitude vertical and sends time
/// away from the viewer toward the upper-right of the display.
pub(crate) fn projection_matrix(rot_x: i8, rot_y: i8, rot_z: i8) -> ([i16; 3], [i16; 3]) {
    let (sx, cx) = sin_cos_q8(rot_x);
    let (sy, cy) = sin_cos_q8(rot_y);
    let (sz, cz) = sin_cos_q8(rot_z);

    // R = Rz * Ry * Rx, Q8 throughout.
    let rotation = [
        [
            mul_q8(cz, cy),
            mul_q8(mul_q8(cz, sy), sx) - mul_q8(sz, cx),
            mul_q8(mul_q8(cz, sy), cx) + mul_q8(sz, sx),
        ],
        [
            mul_q8(sz, cy),
            mul_q8(mul_q8(sz, sy), sx) + mul_q8(cz, cx),
            mul_q8(mul_q8(sz, sy), cx) - mul_q8(cz, sx),
        ],
        [-sy, mul_q8(cy, sx), mul_q8(cy, cx)],
    ];
    let base_x = [384, 0, 90];
    let base_y = [0, -320, -96];
    let mut out_x = [0i16; 3];
    let mut out_y = [0i16; 3];
    for column in 0..3 {
        let mut x = 0;
        let mut y = 0;
        for row in 0..3 {
            x += mul_q8(base_x[row], rotation[row][column]);
            y += mul_q8(base_y[row], rotation[row][column]);
        }
        out_x[column] = x as i16;
        out_y[column] = y as i16;
    }
    (out_x, out_y)
}


/// Match the FPGA: retain fractional bits through the complete dot product.
pub(crate) fn project_offset(coordinates: [i32; 3], coefficients: &[i16; 3]) -> i32 {
    let mut sum = 0;
    for index in 0..3 {
        sum += coordinates[index] * coefficients[index] as i32;
    }
    sum >> 8
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dot_product_rounds_only_after_sum() {
        assert_eq!(project_offset([1, 1, 1], &[128, 128, 128]), 1);
        assert_eq!(project_offset([-1, -1, -1], &[128, 128, 128]), -2);
        assert_eq!(project_offset([1, -1, 1], &[128, 128, 128]), 0);
    }

    #[test]
    fn default_camera_and_five_degree_steps() {
        assert_eq!(projection_matrix(0, 0, 0), ([384, 0, 90], [0, -320, -96]));
        assert_eq!(sin_cos_q8(5), (22, 255));
        assert_eq!(sin_cos_q8(-5), (-22, 255));
        for a in -256..=256 {
            for b in -256..=256 {
                let expected = ((a * b) as f64 / 256.0).round() as i32;
                assert_eq!(mul_q8(a, b), expected);
            }
        }
    }

    #[test]
    fn all_camera_angles_fit_hardware_and_match_dot_product() {
        for x in (-90..=90).step_by(5) {
            for y in (-90..=90).step_by(5) {
                for z in (-90..=90).step_by(5) {
                    let (px, py) = projection_matrix(x, y, z);
                    for row in [px, py] {
                        assert!(row.iter().all(|&v| (-512..512).contains(&v)));
                        for coordinates in [
                            [-256, 0, 0], [254, 255, 240], [-256, 255, 240],
                            [127, 128, 120], [-64, 8, 60],
                        ] {
                            let exact: i64 = coordinates.iter().zip(row)
                                .map(|(&a, b)| a as i64 * b as i64).sum();
                            assert!(exact.abs() < (1 << 23));
                            assert_eq!(project_offset(coordinates, &row), (exact >> 8) as i32);
                        }
                    }
                }
            }
        }
    }
}

