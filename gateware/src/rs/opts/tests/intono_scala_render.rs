#[path="../../../top/intono/fw/src/scale.rs"] mod scale;
#[path="../../../top/intono/fw/src/ui_text.rs"] mod ui_text;
#[path="../../../top/intono/fw/src/ui_canvas.rs"] mod ui_canvas;
#[path="../../../top/intono/fw/src/ui_controls.rs"] mod ui_controls;
#[path="../../../top/intono/fw/src/ui_imported.rs"] mod ui_imported;
fn tuning(degrees:&[i32],period:i32)->scale::Imported {
    let mut record=b"TSC1".to_vec();record.extend((degrees.len() as u16).to_le_bytes());record.extend([0,0]);record.extend(period.to_le_bytes());
    for d in degrees {record.extend(d.to_le_bytes());}
    let mut crc=0xffff_ffffu32;for byte in &record {crc^=*byte as u32;for _ in 0..8 {crc=(crc>>1)^0xedb8_8320u32.wrapping_mul(crc&1);}}
    record.extend((!crc).to_le_bytes());scale::Imported::from_record(&record).unwrap()
}
#[test]fn imported_controls_have_no_orphaned_borders_and_center_single_actions(){
    use ui_controls::{Surface,scale_field};
    for i in [2,5,9] {assert!(scale_field(Surface::Scales,i,true).is_none());}
    for i in [0,2,3,4,5,9] {assert!(scale_field(Surface::Notes,i,true).is_none());}
    for (surface,i) in [(Surface::Notes,8)] {
        let f=scale_field(surface,i,true).unwrap();assert_eq!(2*f.column+f.width,30);
    }
    for surface in [Surface::Scales,Surface::Notes] {for i in 0..16 {assert_eq!(scale_field(surface,i,false),ui_controls::field(surface,i));}}
}
#[test]fn summary_and_interval_plot_cover_entire_period_without_clipping(){
    let table=tuning(&[0,252632,505263,757895,1010526],1200000);
    let mut cells=[0u32;2025];ui_imported::text(&table,8,0,|a,c|cells[a as usize]=c);
    let row=|r:usize|cells[r*45..(r+1)*45].iter().map(|c|char::from((c&127) as u8+32)).collect::<std::string::String>();
    assert!(row(7).contains("USER SLOT 8"));assert!(row(8).contains("5 PITCHES"));assert!(row(9).contains("1200.000"));assert!(!row(13).contains("252.632"));assert!(row(14).contains("252.632"));
    let mut points=std::collections::BTreeSet::new();ui_imported::plot(&table,|p,c|{assert!(p.inside());assert!((p.x-360).pow(2)+(p.y-360).pow(2)<360*360);if p.y==334 {points.insert((p.x,c));}});
    for pitch in [0,252632,505263,757895,1010526,1200000] {assert!(points.iter().any(|(x,_)|*x==156+(pitch as u32*407/1200000) as i32));}
    let many=tuning(&(0..128).map(|i|i*73125).collect::<Vec<_>>(),9600000);
    ui_imported::plot(&many,|p,_|assert!((156..564).contains(&p.x)));
    ui_imported::text(&many,1,0,|a,c|cells[a as usize]=c);let text=cells.iter().map(|c|char::from((c&127)as u8+32)).collect::<std::string::String>();assert!(text.contains("1-6 OF 128"));
    cells.fill(0);ui_imported::text(&table,8,0,|a,c|cells[a as usize]=c);let mut dump=std::string::String::new();ui_imported::plot(&table,|p,c|dump.push_str(&format!("P {} {} {}\n",p.x,p.y,c)));for (a,c) in cells.iter().enumerate(){if c&127!=0 {dump.push_str(&format!("T {a} {c}\n"));}}std::fs::write("/tmp/intono-scala-summary.txt",dump).unwrap();
}

#[test]fn interval_pages_cover_the_last_partial_page_and_clamp() {
 let table=tuning(&(0..128).map(|i|i*73125).collect::<Vec<_>>(),9600000);
 let mut cells=[0u32;2025];ui_imported::text(&table,1,21,|a,c|cells[a as usize]=c);
 let text=cells.iter().map(|c|char::from((c&127)as u8+32)).collect::<String>();
 assert!(text.contains("127: 9213.750c"));assert!(text.contains("128: 9286.875c"));assert!(text.contains("127-128 OF 128 / READ ONLY"));
 assert_eq!(ui_imported::turn_page(0,128,-1),0);assert_eq!(ui_imported::turn_page(21,128,1),21);assert_eq!(ui_imported::turn_page(21,5,1),0);
}

#[test]fn interval_pager_sits_below_list_and_fits_longest_caption(){
 for (surface,index) in [(ui_controls::Surface::Scales,8),(ui_controls::Surface::Notes,10)] {
  let f=ui_controls::scale_field(surface,index,true).unwrap();assert_eq!(f.row,16);
  let left=120+ui_text::ux_column(f.column as usize)*12-4;
  assert!(left>=120+26*12+8);
  let width=ui_text::ux_column((f.column+f.width)as usize)-ui_text::ux_column(f.column as usize);
  assert!(width>= "PAGE 22 OF 22".len());
 }
}
