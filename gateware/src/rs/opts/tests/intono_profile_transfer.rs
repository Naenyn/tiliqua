#[path = "../../../top/intono/fw/src/profile_transfer.rs"]
mod transfer;
use transfer::*;
#[derive(Default)]
struct Memory {
    value: Option<Vec<u8>>,
    writes: usize,
    reads: usize,
}
impl Store for Memory {
    fn read(&mut self, _kind: u8, _slot: u8, b: &mut [u8]) -> Result<Option<usize>, u8> {
        self.reads += 1;
        Ok(self.value.as_ref().map(|v| {
            b[..v.len()].copy_from_slice(v);
            v.len()
        }))
    }
    fn write(&mut self, _kind: u8, _slot: u8, b: &[u8]) -> Result<(), u8> {
        self.writes += 1;
        self.value = Some(b.to_vec());
        Ok(())
    }
}
fn request(
    e: &mut Exchange,
    s: &mut Memory,
    op: u8,
    kind: u8,
    slot: u8,
    offset: usize,
    data: &[u8],
    total: usize,
    now: u64,
    busy: bool,
) -> [u8; FRAME] {
    let mut p = [0; FRAME];
    p[..6].copy_from_slice(&[b'I', b'P', op, 17, kind, slot]);
    p[6..8].copy_from_slice(&(offset as u16).to_le_bytes());
    p[8] = data.len() as u8;
    p[10..12].copy_from_slice(&(total as u16).to_le_bytes());
    p[12..12 + data.len()].copy_from_slice(data);
    p[31] = crc(&p[..31]);
    for (i, b) in p.iter().enumerate() {
        assert_eq!(e.feed(*b, now + i as u64), i == 31);
    }
    e.respond(now + 32, busy, s);
    let r = e.tx;
    assert_eq!(r[31], crc(&r[..31]));
    e.sent = FRAME;
    r
}
#[test]
fn complete_read_and_upload_only_commits_once() {
    let mut e = Exchange::new();
    let mut s = Memory {
        value: Some((0..=255).cycle().take(CAPACITY).collect()),
        ..Memory::default()
    };
    let data = s.value.clone().unwrap();
    for offset in (0..CAPACITY).step_by(CHUNK) {
        let r = request(&mut e, &mut s, 2, 0, 1, offset, &[], 0, 100, false);
        assert_eq!(r[9], OK);
        assert_eq!(u16::from_le_bytes([r[10], r[11]]) as usize, CAPACITY);
        assert_eq!(
            &r[12..12 + r[8] as usize],
            &data[offset..(offset + CHUNK).min(CAPACITY)]
        );
    }
    assert_eq!(s.reads, 1);
    assert_eq!(
        request(&mut e, &mut s, 3, 0, 1, 0, &[], CAPACITY, 100, false)[9],
        OK
    );
    for offset in (0..CAPACITY).step_by(CHUNK) {
        assert_eq!(
            request(
                &mut e,
                &mut s,
                4,
                0,
                1,
                offset,
                &data[offset..(offset + CHUNK).min(CAPACITY)],
                0,
                100,
                false
            )[9],
            OK
        );
        assert_eq!(s.writes, 0);
    }
    assert_eq!(
        request(&mut e, &mut s, 5, 0, 1, 0, &[], 0, 100, false)[9],
        OK
    );
    assert_eq!(s.writes, 1);
    assert_eq!(s.value, Some(data));
    assert_eq!(
        request(&mut e, &mut s, 5, 0, 1, 0, &[], 0, 100, false)[9],
        ORDER
    );
    assert_eq!(s.writes, 1);
}
#[test]
fn rejects_busy_bad_slots_order_truncation_and_expiry() {
    let mut e = Exchange::new();
    let mut s = Memory::default();
    assert_eq!(
        request(&mut e, &mut s, 2, 0, 1, 0, &[], 0, 100, false)[9],
        EMPTY
    );
    for (kind, slot) in [(2, 1), (0, 0), (1, 9)] {
        assert_eq!(
            request(&mut e, &mut s, 3, kind, slot, 0, &[], 10, 100, false)[9],
            INVALID
        );
    }
    assert_eq!(
        request(&mut e, &mut s, 3, 0, 1, 0, &[], CAPACITY + 1, 100, false)[9],
        INVALID
    );
    assert_eq!(
        request(&mut e, &mut s, 3, 0, 1, 0, &[], 10, 100, true)[9],
        BUSY
    );
    request(&mut e, &mut s, 3, 0, 1, 0, &[], 10, 100, false);
    assert_eq!(
        request(&mut e, &mut s, 4, 0, 1, 1, &[5], 0, 100, false)[9],
        ORDER
    );
    assert_eq!(
        request(&mut e, &mut s, 5, 0, 1, 0, &[], 0, 100, false)[9],
        ORDER
    );
    request(&mut e, &mut s, 4, 0, 1, 0, &[5; 10], 0, 100, false);
    assert!(!e.active(20_000));
    assert_eq!(
        request(&mut e, &mut s, 5, 0, 1, 0, &[], 0, 20_000, false)[9],
        ORDER
    );
    assert_eq!(s.writes, 0);
    request(&mut e, &mut s, 3, 0, 1, 0, &[], 10, 100, false);
    request(&mut e, &mut s, 4, 0, 1, 0, &[5; 10], 0, 100, false);
    assert_eq!(
        request(&mut e, &mut s, 5, 0, 1, 0, &[], 0, 100, true)[9],
        BUSY
    );
    assert_eq!(s.writes, 0);
}
#[test]
fn corrupt_and_expired_frames_never_form_requests() {
    let mut e = Exchange::new();
    assert!(!e.feed(73, 1));
    assert!(!e.feed(80, 2400));
    let mut p = [0; FRAME];
    p[..3].copy_from_slice(&[73, 80, 1]);
    p[31] = crc(&p[..31]) ^ 1;
    for b in p {
        assert!(!e.feed(b, 2401));
    }
    let mut s = Memory::default();
    assert_eq!(
        request(&mut e, &mut s, 1, 0, 1, 0, &[], 0, 2500, false)[12],
        1
    );
    assert_eq!(s.reads, 0);
    assert_eq!(s.writes, 0);
}

#[test]
fn partial_packet_survives_a_foreground_scene_redraw() {
    let mut e = Exchange::new();
    let mut packet = [0; FRAME];
    packet[..6].copy_from_slice(&[73, 80, 1, 42, 0, 1]);
    packet[31] = crc(&packet[..31]);
    for byte in &packet[..8] { assert!(!e.feed(*byte, 1)); }
    for (index, byte) in packet[8..].iter().enumerate() {
        assert_eq!(e.feed(*byte, 1500), index == FRAME - 9);
    }
    let mut store = Memory::default();
    e.respond(1500, false, &mut store);
    assert_eq!(e.tx[9], OK);
    assert_eq!(&e.tx[12..16], &[1, 8, 16, 8]);
    assert_eq!(store.writes, 0);
}
