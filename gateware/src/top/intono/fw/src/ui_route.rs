//! User-facing route feedback; engine status and diagnostic logging stay intact.
pub fn status_message(status: &'static str) -> Option<&'static str> {
    Some(match status {
        "STOPPED" | "STOPPED BY USER" | "STOPPED - RUN TO START" => return None,
        "BIND CORRECTION ON ROUTE FIRST" => "APPLY PROFILE BEFORE START",
        "CHOOSE SCALE OR CORRECTION" => "ENABLE SCALE OR CHOOSE PROFILE",
        "STOP THIS OUTPUT BEFORE BINDING" => "STOP THIS OUTPUT BEFORE APPLY",
        "BOUND - NATURAL NOTE SET" => "PROFILE APPLIED - 0V NOTE SET",
        "BOUND - NO MEASURED 0V REFERENCE" => "APPLIED - NO MEASURED 0V NOTE",
        "CANNOT BIND PROFILE" => "CANNOT APPLY PROFILE",
        other => other,
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stopped_faults_and_action_errors_remain_visible() {
        for status in ["STOPPED - CV STALE", "STOPPED - OUTPUT FAULT",
            "STOPPED - OUTPUT NO ACK", "STOPPED - INVALID SCALE",
            "EMPTY PROFILE SLOT", "STOP OUTPUTS BEFORE FLASH READ"] {
            assert_eq!(status_message(status),Some(status));
        }
        assert_eq!(status_message("STOPPED BY USER"),None);
        assert!(status_message("BIND CORRECTION ON ROUTE FIRST").unwrap().contains("APPLY PROFILE"));
    }
}
