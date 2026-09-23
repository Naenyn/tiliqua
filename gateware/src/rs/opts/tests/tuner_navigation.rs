#[path="../../../top/intono/fw/src/options.rs"] mod options;
use opts::*;
use strum::IntoEnumIterator;

#[test] fn tuner_children_have_safe_labels_but_do_not_clutter_root_navigation() {
    use options::Page;
    assert_eq!(Page::iter().count(),6);
    for child in [Page::Verify,Page::Profiles,Page::QuantNotes,Page::QuantSetups] {
        assert!(!Page::iter().any(|p|p==child));
        let label:&'static str=child.into();assert!(!label.is_empty());
    }
    let mut opts=options::Opts::default();
    for page in [Page::Tuner,Page::Calibrate,Page::Verify,Page::Profiles,Page::Settings,
                 Page::Help,Page::Play,Page::Quantizer,Page::QuantNotes,Page::QuantSetups] {
        opts.tracker.page.value=page;
        assert!(!opts.page().value().is_empty());
        assert!(opts.view().options().len()<=8);
    }
    assert_eq!(options::Correction::iter().count(),10);
}
