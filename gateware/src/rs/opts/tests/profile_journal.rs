//! Exercise the actual flash journal, including torn programming and GC.
use opts::persistence::{FlashOptionsPersistence,OptionsPersistence};
use embedded_storage::nor_flash::{ErrorType,NorFlash,ReadNorFlash,MultiwriteNorFlash,NorFlashError,NorFlashErrorKind};
use std::{cell::RefCell,rc::Rc};

#[derive(Debug,Clone,Copy)] struct PowerLoss;
impl NorFlashError for PowerLoss {fn kind(&self)->NorFlashErrorKind{NorFlashErrorKind::Other}}
#[derive(Clone)] struct State {bytes:Vec<u8>,remaining:Option<usize>,erases:usize}
#[derive(Clone)] struct Flash(Rc<RefCell<State>>);
impl ErrorType for Flash {type Error=PowerLoss;}
impl ReadNorFlash for Flash {
    const READ_SIZE:usize=1;
    fn read(&mut self,offset:u32,bytes:&mut [u8])->Result<(),PowerLoss> {
        bytes.copy_from_slice(&self.0.borrow().bytes[offset as usize..offset as usize+bytes.len()]);Ok(())
    }
    fn capacity(&self)->usize {self.0.borrow().bytes.len()}
}
impl NorFlash for Flash {
    const WRITE_SIZE:usize=1;const ERASE_SIZE:usize=4096;
    fn write(&mut self,offset:u32,bytes:&[u8])->Result<(),PowerLoss> {
        let mut s=self.0.borrow_mut();
        for (i,b) in bytes.iter().enumerate() {
            if let Some(left)=s.remaining.as_mut() {if *left==0{return Err(PowerLoss);}*left-=1;}
            let dest=&mut s.bytes[offset as usize+i];assert_eq!(*dest&*b,*b);*dest&=*b;
        }Ok(())
    }
    fn erase(&mut self,from:u32,to:u32)->Result<(),PowerLoss> {
        let mut s=self.0.borrow_mut();
        s.erases+=1;
        for i in from as usize..to as usize {
            if let Some(left)=s.remaining.as_mut() {if *left==0{return Err(PowerLoss);}*left-=1;}
            s.bytes[i]=255;
        }Ok(())
    }
}
impl MultiwriteNorFlash for Flash {}
fn blank()->Flash {Flash(Rc::new(RefCell::new(State{bytes:vec![255;8192],remaining:None,erases:0})))}
type Journal=FlashOptionsPersistence<Flash,384>;
fn open(flash:&Flash)->Journal {Journal::with_buffer(flash.clone(),0..8192)}
const KEY:u32=0x54555031;

#[path="../../../top/tuner/fw/src/note_pattern.rs"] mod tuner_notes;
#[test] fn tuner_note_record_survives_gc_without_changing_profiles() {
    let f=expanded_flash();
    let mut storage=ExpandedJournal::with_reserved_buffer(f.clone(),0..8192,0..24576).unwrap();
    for slot in 0..4 {storage.save_key_in(8192..24576,KEY+slot,&[slot as u8;1008]).unwrap();}
    let profiles=f.0.borrow().bytes[8192..].to_vec();
    for mask in 0..500u16 {
        let bytes=tuner_notes::encode([mask,0xfff^mask]).unwrap();
        storage.save_key(tuner_notes::KEY,&bytes).unwrap();
    }
    let mut storage=ExpandedJournal::with_reserved_buffer(f.clone(),0..8192,0..24576).unwrap();
    let mut bytes=[0;13];
    let n=storage.load_key(tuner_notes::KEY,&mut bytes).unwrap().unwrap();
    assert_eq!(tuner_notes::decode(&bytes[..n]),Some([499,0xfff^499]));
    assert_eq!(&f.0.borrow().bytes[8192..],profiles);
}

// Proposed TUNER layout: leave the legacy 8 KiB options/profile journal
// untouched and use a separate 16 KiB journal for expanded profiles. Tests
// exercise real GC; production must explicitly reserve this in its manifest.
type ExpandedJournal=FlashOptionsPersistence<Flash,1100>;
fn expanded(f:&Flash)->ExpandedJournal {ExpandedJournal::with_buffer(f.clone(),8192..24576)}
fn expanded_flash()->Flash {
    Flash(Rc::new(RefCell::new(State{bytes:vec![255;24576],remaining:None,erases:0})))
}

#[test] fn single_owner_isolates_journals_and_rejects_unreserved_or_overlapping_windows() {
    let f=expanded_flash();
    let mut storage=ExpandedJournal::with_reserved_buffer(f.clone(),0..8192,0..24576).unwrap();
    storage.save_key(KEY,&[42;296]).unwrap();
    let legacy=f.0.borrow().bytes[..8192].to_vec();
    for version in 0..100u8 {
        storage.save_key_in(8192..24576,KEY+(version%4) as u32,&[version;1008]).unwrap();
    }
    assert_eq!(&f.0.borrow().bytes[..8192],legacy);
    let mut bytes=[0;1008];
    for slot in 0..4 {
        assert_eq!(storage.load_key_in(8192..24576,KEY+slot,&mut bytes).unwrap(),Some(1008));
        assert_eq!(bytes,[96+slot as u8;1008]);
    }
    assert_eq!(storage.load_key(KEY,&mut bytes).unwrap(),Some(296));
    assert_eq!(&bytes[..296],&[42;296]);
    let before=f.0.borrow().bytes.clone();
    for window in [0..24576,4096..12288,8193..24576,8192..28672,8192..8192,16384..8192,8192..12288] {
        assert!(storage.save_key_in(window.clone(),KEY,&[7;10]).is_err());
        assert!(storage.load_key_in(window,KEY,&mut bytes).is_err());
    }
    assert_eq!(before,f.0.borrow().bytes);
    let mut short=[99;100];
    assert!(storage.load_key_in(8192..24576,KEY,&mut short).is_err());
    assert_eq!(short,[99;100]);
    assert_eq!(storage.default_window(),0..8192);
    for (default,reserved) in [(0..8192,0..28672),(0..8192,1..24576),(0..4096,0..24576),
        (0..12288,4096..24576),(8192..0,0..24576)] {
        assert!(ExpandedJournal::with_reserved_buffer(f.clone(),default,reserved).is_err());
    }
}

#[test] fn expanded_profiles_have_gc_headroom_without_changing_legacy_journal() {
    let f=expanded_flash();
    open(&f).save_key(KEY,&[42;296]).unwrap();
    let legacy=f.0.borrow().bytes[..8192].to_vec();
    for slot in 0..4 {expanded(&f).save_key(KEY+slot,&[slot as u8;1008]).unwrap();}
    for version in 0..100u8 {
        expanded(&f).save_key(KEY+(version%4) as u32,&[version;1008]).unwrap();
    }
    let mut bytes=[0;1008];
    for slot in 0..4 {
        assert_eq!(expanded(&f).load_key(KEY+slot,&mut bytes).unwrap(),Some(1008));
        assert_eq!(bytes,[96+slot as u8;1008]);
    }
    assert_eq!(&f.0.borrow().bytes[..8192],legacy);
    assert_eq!(open(&f).load_key(KEY,&mut bytes).unwrap(),Some(296));
    assert_eq!(&bytes[..296],&[42;296]);
}

#[test] fn expanded_profile_torn_gc_preserves_old_or_new_and_legacy_bytes() {
    let f=expanded_flash();open(&f).save_key(KEY,&[42;296]).unwrap();
    for slot in 0..4 {expanded(&f).save_key(KEY+slot,&[slot as u8+10;1008]).unwrap();}
    let mut found=false;
    for _ in 0..100 {
        let before=f.0.borrow().clone();
        expanded(&f).save_key(KEY,&[10;1008]).unwrap();
        if f.0.borrow().erases>before.erases {*f.0.borrow_mut()=before;found=true;break;}
    }
    assert!(found);
    let baseline=f.0.borrow().clone();
    for cut in (0..16000).step_by(73) {
        let interrupted=Flash(Rc::new(RefCell::new(baseline.clone())));
        interrupted.0.borrow_mut().remaining=Some(cut);
        let _=expanded(&interrupted).save_key(KEY,&[99;1008]);
        interrupted.0.borrow_mut().remaining=None;
        let mut bytes=[0;1008];
        assert_eq!(expanded(&interrupted).load_key(KEY,&mut bytes).unwrap(),Some(1008),"cut {cut}");
        assert!(bytes==[10;1008] || bytes==[99;1008],"cut {cut}");
        for slot in 1..4 {
            assert_eq!(expanded(&interrupted).load_key(KEY+slot,&mut bytes).unwrap(),Some(1008));
            assert_eq!(bytes,[slot as u8+10;1008]);
        }
        assert_eq!(&interrupted.0.borrow().bytes[..8192],&baseline.bytes[..8192]);
    }
}

#[test] fn four_profiles_survive_many_updates_and_reopen() {
    let flash=blank();let mut storage=open(&flash);
    for slot in 0..4 {storage.save_key(KEY+slot,&[slot as u8;296]).unwrap();}
    for i in 0..30 {storage.save_key(100+i,&[i as u8;24]).unwrap();}
    for version in 0..80u8 {storage.save_key(KEY,&[version;296]).unwrap();}
    let mut storage=open(&flash);let mut buf=[0;296];
    for slot in 0..4 {
        assert_eq!(storage.load_key(KEY+slot,&mut buf).unwrap(),Some(296));
        assert_eq!(buf,[if slot==0 {79} else {slot as u8};296]);
    }
    for i in 0..30 {assert_eq!(storage.load_key(100+i,&mut buf).unwrap(),Some(24));assert_eq!(&buf[..24],&[i as u8;24]);}
}

#[test] fn torn_overwrites_recover_old_or_new_record_not_a_mixture() {
    let flash=blank();let mut storage=open(&flash);
    for slot in 0..4 {storage.save_key(KEY+slot,&[slot as u8+10;296]).unwrap();}
    // Test both ordinary programming and a nearly full page that needs GC.
    for needs_gc in [false,true] {
        let working=Flash(Rc::new(RefCell::new(flash.0.borrow().clone())));
        if needs_gc {
            let mut found=false;
            for _ in 0..100 {
                let before=working.0.borrow().clone();
                open(&working).save_key(KEY,&[10;296]).unwrap();
                if working.0.borrow().erases>before.erases {
                    *working.0.borrow_mut()=before;found=true;break;
                }
            }
            assert!(found,"must actually exercise garbage collection");
        }
        for cut in (0..10000).step_by(if needs_gc {97} else {1}) {
            let f=Flash(Rc::new(RefCell::new(working.0.borrow().clone())));
            f.0.borrow_mut().remaining=Some(cut);
            let _=open(&f).save_key(KEY,&[99;296]);
            f.0.borrow_mut().remaining=None;
            let mut reopened=open(&f);let mut bytes=[0;296];
            assert_eq!(reopened.load_key(KEY,&mut bytes).unwrap(),Some(296),"cut {cut}");
            assert!(bytes==[10;296] || bytes==[99;296],"cut {cut}");
            for slot in 1..4 {
                assert_eq!(reopened.load_key(KEY+slot,&mut bytes).unwrap(),Some(296));
                assert_eq!(bytes,[slot as u8+10;296]);
            }
            if !needs_gc && cut>400 {break;}
        }
    }
}

use opts::*;
use serde_derive::{Serialize,Deserialize};
use strum_macros::{EnumIter,IntoStaticStr};
#[derive(Clone,Copy,PartialEq,Default,EnumIter,IntoStaticStr,Serialize,Deserialize)] enum Page {#[default] Settings}
int_params!(Params<u8>{step:1,min:0,max:10});
#[derive(OptionPage,Clone)] struct Settings {#[option(0)] value:IntOption<Params>}
#[derive(Options,Clone)] struct TestOptions {tracker:ScreenTracker<Page>,#[page(Page::Settings)] settings:Settings}
#[test] fn resetting_options_does_not_remove_profiles_and_default_constructor_still_works() {
    let flash=blank();let mut storage=open(&flash);let mut opts=TestOptions::default();opts.settings.value.value=3;
    storage.save_options(&opts).unwrap();storage.save_key(KEY,&[5;296]).unwrap();
    storage.erase_options(&opts).unwrap();let mut buf=[0;296];
    assert_eq!(storage.load_key(KEY,&mut buf).unwrap(),Some(296));assert_eq!(buf,[5;296]);
    assert_eq!(storage.load_key(opts.settings.value.key().value(),&mut buf).unwrap(),None);
    let fresh=blank();let mut legacy=FlashOptionsPersistence::new(fresh,0..8192);
    legacy.save_key(42,&[7]).unwrap();assert_eq!(legacy.load_key(42,&mut buf).unwrap(),Some(1));
}
