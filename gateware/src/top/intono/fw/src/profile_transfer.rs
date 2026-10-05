//! Bounded, stop-and-wait profile exchange. No allocation or arbitrary flash keys.
//! Packet layout and browser implementation: web/intono/protocol.mjs.
pub const FRAME: usize = 32;
pub const CHUNK: usize = 16;
pub const CAPACITY: usize = 1100;
pub const OK: u8 = 0;
pub const EMPTY: u8 = 1;
pub const BUSY: u8 = 2;
pub const ORDER: u8 = 3;
pub const INVALID: u8 = 4;
pub const IO: u8 = 5;

pub trait Store {
    fn read(&mut self, kind: u8, slot: u8, bytes: &mut [u8]) -> Result<Option<usize>, u8>;
    fn write(&mut self, kind: u8, slot: u8, bytes: &[u8]) -> Result<(), u8>;
}
pub fn crc(bytes: &[u8]) -> u8 {
    let mut c = 0u8;
    for b in bytes {
        c ^= b;
        for _ in 0..8 {
            c = (c << 1) ^ if c & 128 != 0 { 7 } else { 0 };
        }
    }
    c
}
pub struct Exchange {
    rx: [u8; FRAME],
    used: usize,
    pub tx: [u8; FRAME],
    pub sent: usize,
    bytes: [u8; CAPACITY],
    length: usize,
    received: usize,
    kind: u8,
    slot: u8,
    mode: u8,
    deadline: u64,
    rx_deadline: u64,
}
impl Exchange {
    pub const fn new() -> Self {
        Self {
            rx: [0; FRAME],
            used: 0,
            tx: [0; FRAME],
            sent: FRAME,
            bytes: [0; CAPACITY],
            length: 0,
            received: 0,
            kind: 0,
            slot: 0,
            mode: 0,
            deadline: 0,
            rx_deadline: 0,
        }
    }
    pub fn active(&mut self, now: u64) -> bool {
        if self.deadline != 0 && now >= self.deadline {
            self.mode = 0;
            self.deadline = 0;
        }
        self.sent < FRAME || now < self.deadline
    }
    /// Idle partial frames have a separate short expiry; they never reserve UART.
    pub fn feed(&mut self, byte: u8, now: u64) -> bool {
        if now >= self.rx_deadline {
            self.used = 0;
        }
        self.rx_deadline = now.saturating_add(250);
        if self.used == 0 && byte != b'I' {
            return false;
        }
        if self.used == 1 && byte != b'P' {
            self.used = usize::from(byte == b'I');
            return false;
        }
        self.rx[self.used] = byte;
        self.used += 1;
        if self.used != FRAME {
            return false;
        }
        self.used = 0;
        self.rx[31] == crc(&self.rx[..31])
    }
    pub fn respond(&mut self, now: u64, busy: bool, store: &mut impl Store) {
        let op = self.rx[2];
        let kind = self.rx[4];
        let slot = self.rx[5];
        let offset = u16::from_le_bytes([self.rx[6], self.rx[7]]) as usize;
        let count = self.rx[8] as usize;
        let total = u16::from_le_bytes([self.rx[10], self.rx[11]]) as usize;
        self.deadline = now.saturating_add(10_000);
        self.tx = [0; FRAME];
        self.tx[..2].copy_from_slice(b"IR");
        self.tx[2..8].copy_from_slice(&self.rx[2..8]);
        let status = if op == 1 {
            // Version, slots per kind, chunk size; no persistent state is changed.
            self.tx[8] = 4;
            self.tx[12..16].copy_from_slice(&[1, 8, CHUNK as u8, 8]);
            OK
        } else if op == 6 {
            self.mode = 0;
            OK
        } else if kind > 1 || !(1..=8).contains(&slot) || count > CHUNK {
            INVALID
        } else if busy {
            self.mode = 0;
            BUSY
        } else {
            match op {
                2 => {
                    let loaded = if offset == 0 {
                        self.mode = 0;
                        match store.read(kind, slot, &mut self.bytes) {
                            Ok(Some(n)) if n <= CAPACITY => {
                                self.length = n;
                                self.kind = kind;
                                self.slot = slot;
                                self.mode = 1;
                                OK
                            }
                            Ok(None) => EMPTY,
                            Err(e) => e,
                            _ => IO,
                        }
                    } else if self.mode == 1 && self.kind == kind && self.slot == slot {
                        OK
                    } else {
                        ORDER
                    };
                    if loaded != OK {
                        loaded
                    } else if offset >= self.length {
                        ORDER
                    } else {
                        let n = CHUNK.min(self.length - offset);
                        self.tx[8] = n as u8;
                        self.tx[10..12].copy_from_slice(&(self.length as u16).to_le_bytes());
                        self.tx[12..12 + n].copy_from_slice(&self.bytes[offset..offset + n]);
                        OK
                    }
                }
                3 => {
                    self.mode = 0;
                    if total == 0 || total > CAPACITY {
                        INVALID
                    } else {
                        self.length = total;
                        self.received = 0;
                        self.kind = kind;
                        self.slot = slot;
                        self.mode = 2;
                        OK
                    }
                }
                4 => {
                    if self.mode != 2
                        || self.kind != kind
                        || self.slot != slot
                        || offset != self.received
                        || count == 0
                        || offset + count > self.length
                    {
                        ORDER
                    } else {
                        self.bytes[offset..offset + count]
                            .copy_from_slice(&self.rx[12..12 + count]);
                        self.received += count;
                        OK
                    }
                }
                5 => {
                    if self.mode != 2
                        || self.kind != kind
                        || self.slot != slot
                        || self.received != self.length
                    {
                        ORDER
                    } else {
                        self.mode = 0;
                        store
                            .write(kind, slot, &self.bytes[..self.length])
                            .err()
                            .unwrap_or(OK)
                    }
                }
                _ => INVALID,
            }
        };
        self.tx[9] = status;
        self.tx[31] = crc(&self.tx[..31]);
        self.sent = 0;
    }
}
