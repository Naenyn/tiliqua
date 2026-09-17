//! A help acknowledgement separate from the user's saved sound.
//! REZO-family journals store one short record per 4 KiB sector. Reserve
//! the last four bytes of sector zero; never erase a sector to set this flag.

pub const HELP_SEEN_OFFSET: u16 = 4092;
const HELP_SEEN_TAG: [u8; 4] = *b"HELP";

pub fn should_show_first_help(enabled: bool, have_defaults: bool, seen: Option<bool>) -> bool {
    enabled && !have_defaults && seen == Some(false)
}

pub fn read_help_seen(mut read: impl FnMut(u16) -> Option<u8>) -> Option<bool> {
    let mut seen = true;
    for (n, byte) in HELP_SEEN_TAG.iter().enumerate() {
        seen &= read(HELP_SEEN_OFFSET + n as u16)? == *byte;
    }
    Some(seen)
}

pub fn mark_help_seen(
    mut program: impl FnMut(u16, u8) -> bool,
    read: impl FnMut(u16) -> Option<u8>,
) -> bool {
    for (n, byte) in HELP_SEEN_TAG.iter().enumerate() {
        if !program(HELP_SEEN_OFFSET + n as u16, *byte) {
            return false;
        }
    }
    read_help_seen(read) == Some(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use core::cell::RefCell;

    #[test]
    fn first_help_policy_handles_defaults_disabled_flag_and_read_errors() {
        assert!(should_show_first_help(true, false, Some(false)));
        assert!(!should_show_first_help(true, false, Some(true)));
        assert!(!should_show_first_help(true, true, Some(false)));
        assert!(!should_show_first_help(false, false, Some(false)));
        assert!(!should_show_first_help(true, false, None));
    }

    #[test]
    fn acknowledgement_only_programs_footer_and_survives_reboot() {
        let flash = RefCell::new([0xff; 4096]);
        flash.borrow_mut()[..96].fill(0x5a);
        assert_eq!(
            read_help_seen(|o| Some(flash.borrow()[o as usize])),
            Some(false)
        );
        let mut writes = 0;
        assert!(mark_help_seen(
            |o, b| {
                assert!(o >= HELP_SEEN_OFFSET);
                flash.borrow_mut()[o as usize] &= b;
                writes += 1;
                true
            },
            |o| Some(flash.borrow()[o as usize])
        ));
        assert_eq!(writes, 4);
        assert!(flash.borrow()[..96].iter().all(|b| *b == 0x5a));
        assert!(flash.borrow()[96..4092].iter().all(|b| *b == 0xff));
        assert_eq!(
            read_help_seen(|o| Some(flash.borrow()[o as usize])),
            Some(true)
        );
    }

    #[test]
    fn interrupted_acknowledgement_reappears_and_can_be_retried_without_erasing() {
        let flash = RefCell::new([0xff; 4096]);
        assert!(!mark_help_seen(
            |o, b| {
                if o == HELP_SEEN_OFFSET + 2 {
                    return false;
                }
                flash.borrow_mut()[o as usize] &= b;
                true
            },
            |o| Some(flash.borrow()[o as usize])
        ));
        assert_eq!(
            read_help_seen(|o| Some(flash.borrow()[o as usize])),
            Some(false)
        );
        assert!(mark_help_seen(
            |o, b| {
                flash.borrow_mut()[o as usize] &= b;
                true
            },
            |o| Some(flash.borrow()[o as usize])
        ));
        assert!(!mark_help_seen(|_, _| true, |_| None));
    }
}
