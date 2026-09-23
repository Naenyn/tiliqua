use sequential_storage::map::{fetch_item, store_item, remove_all_items};
use sequential_storage::cache::NoCache;
use embassy_futures::block_on;
use embassy_embedded_hal::adapter::BlockingAsync;

use crate::traits::Options;

const DATA_BUFFER_SZ: usize = 32;
const DEFAULT_PAGE_KEY: u32 = 0xdeadbeef;

#[derive(Debug)]
pub enum PersistenceError {
    StorageError,
    SerializationError,
    FlashRangeError,
}

pub trait OptionsPersistence {
    type Error;

    fn save_key(&mut self, key: u32, value: &[u8]) -> Result<(), Self::Error>;
    fn save_key_retries(&mut self, key: u32, value: &[u8], retries: usize) -> Result<(), Self::Error>;
    fn load_key(&mut self, key: u32, buffer: &mut [u8]) -> Result<Option<usize>, Self::Error>;

    fn erase_all(&mut self) -> Result<(), Self::Error>;
    fn load_options<O: Options>(&mut self, opts: &mut O) -> Result<(), Self::Error>;
    fn save_options<O: Options>(&mut self, opts: &O) -> Result<(), Self::Error>;
}

pub struct FlashOptionsPersistence<F, const BUFFER_SIZE: usize = DATA_BUFFER_SZ> {
    flash: BlockingAsync<F>,
    flash_range: core::ops::Range<u32>,
    reserved_range: core::ops::Range<u32>,
    data_buffer: [u8; BUFFER_SIZE],
}

impl<F> FlashOptionsPersistence<F> {
    pub fn new(flash: F, flash_range: core::ops::Range<u32>) -> Self {
        Self::with_buffer(flash, flash_range)
    }
}

impl<F, const BUFFER_SIZE: usize> FlashOptionsPersistence<F, BUFFER_SIZE> {
    /// Opt-in capacity for larger records. Existing callers retain 32 bytes.
    pub fn with_buffer(flash: F, flash_range: core::ops::Range<u32>) -> Self {
        Self {
            flash: BlockingAsync::new(flash),
            reserved_range: flash_range.clone(),
            flash_range,
            data_buffer: [0u8; BUFFER_SIZE],
        }
    }
}

impl<F, const BUFFER_SIZE: usize> FlashOptionsPersistence<F, BUFFER_SIZE>
where F: embedded_storage::nor_flash::NorFlash + embedded_storage::nor_flash::MultiwriteNorFlash {
    /// One flash owner and scratch buffer, with a separately reserved region.
    /// The default journal retains its original geometry (including its GC).
    pub fn with_reserved_buffer(flash:F, default:core::ops::Range<u32>,
                                reserved:core::ops::Range<u32>)->Result<Self,PersistenceError> {
        let page=F::ERASE_SIZE as u32;
        if page==0 || reserved.start>=reserved.end || reserved.end as usize>flash.capacity()
            || reserved.start%page!=0 || reserved.end%page!=0
            || default.start<reserved.start || default.end>reserved.end
            || default.end.checked_sub(default.start).unwrap_or(0)<2*page
            || default.start%page!=0 || default.end%page!=0 {
            return Err(PersistenceError::FlashRangeError);
        }
        let mut storage=Self::with_buffer(flash,default);
        storage.reserved_range=reserved;Ok(storage)
    }

    pub fn default_window(&self)->core::ops::Range<u32> {self.flash_range.clone()}

    fn check_window(&self,window:&core::ops::Range<u32>)->Result<(),PersistenceError> {
        let page=F::ERASE_SIZE as u32;
        if page==0 || window.start<self.reserved_range.start || window.end>self.reserved_range.end
            || window.end.checked_sub(window.start).unwrap_or(0)<2*page
            || window.start%page!=0 || window.end%page!=0
            || (window!=&self.flash_range && window.start<self.flash_range.end
                && window.end>self.flash_range.start) {
            return Err(PersistenceError::FlashRangeError);
        }
        Ok(())
    }

    /// Explicit journals never change the default used for menu settings.
    pub fn save_key_in(&mut self,window:core::ops::Range<u32>,key:u32,value:&[u8])
        ->Result<(),PersistenceError> {
        self.check_window(&window)?;
        block_on(store_item::<u32,&[u8],_>(&mut self.flash,window,&mut NoCache::new(),
            &mut self.data_buffer,&key,&value)).map_err(|_|PersistenceError::StorageError)
    }

    pub fn load_key_in(&mut self,window:core::ops::Range<u32>,key:u32,buffer:&mut [u8])
        ->Result<Option<usize>,PersistenceError> {
        self.check_window(&window)?;
        let item=block_on(fetch_item::<u32,&[u8],_>(&mut self.flash,window,&mut NoCache::new(),
            &mut self.data_buffer,&key)).map_err(|_|PersistenceError::StorageError)?;
        match item {
            Some(data) if data.len()<=buffer.len()=>{
                buffer[..data.len()].copy_from_slice(data);Ok(Some(data.len()))
            }
            Some(_)=>Err(PersistenceError::SerializationError),
            None=>Ok(None),
        }
    }

    /// Remove menu settings without destroying other records in this journal.
    pub fn erase_options<O: Options>(&mut self, opts: &O) -> Result<(), PersistenceError> {
        for key in opts.all().map(|o| o.key().value()).chain(core::iter::once(DEFAULT_PAGE_KEY)) {
            block_on(sequential_storage::map::remove_item::<u32, _>(
                &mut self.flash, self.flash_range.clone(), &mut NoCache::new(),
                &mut self.data_buffer, &key,
            )).map_err(|_| PersistenceError::StorageError)?;
        }
        Ok(())
    }
}

impl<F, const BUFFER_SIZE: usize> OptionsPersistence for FlashOptionsPersistence<F, BUFFER_SIZE>
where
    F: embedded_storage::nor_flash::NorFlash + embedded_storage::nor_flash::MultiwriteNorFlash,
{
    type Error = PersistenceError;

    fn save_key(&mut self, key: u32, value: &[u8]) -> Result<(), Self::Error> {
        block_on(store_item::<u32, &[u8], _>(
            &mut self.flash,
            self.flash_range.clone(),
            &mut NoCache::new(),
            &mut self.data_buffer,
            &key,
            &value,
        )).map_err(|_| PersistenceError::StorageError)
    }

    fn save_key_retries(&mut self, key: u32, value: &[u8], retries: usize) -> Result<(), Self::Error> {
        let mut result = Ok(());
        for _ in 0..retries {
            result = self.save_key(key, value);
            if result.is_ok() {
                return result;
            } else {
                log::warn!("save_key_retries: failed once with {:?}", result);
            }
        }
        return result;
    }

    fn load_key(&mut self, key: u32, buffer: &mut [u8]) -> Result<Option<usize>, Self::Error> {
        let item = block_on(fetch_item::<u32, &[u8], _>(
            &mut self.flash,
            self.flash_range.clone(),
            &mut NoCache::new(),
            &mut self.data_buffer,
            &key,
        )).map_err(|_| PersistenceError::StorageError)?;
        if let Some(data) = item {
            let len = data.len().min(buffer.len());
            buffer[..len].copy_from_slice(&data[..len]);
            Ok(Some(len))
        } else {
            Ok(None)
        }
    }

    fn erase_all(&mut self) -> Result<(), Self::Error> {
        block_on(remove_all_items::<u32, _>(
            &mut self.flash,
            self.flash_range.clone(),
            &mut NoCache::new(),
            &mut self.data_buffer,
        )).map_err(|_| PersistenceError::StorageError)
    }

    fn save_options<O: Options>(&mut self, opts: &O) -> Result<(), Self::Error> {
        for opt in opts.all() {
            let mut buf: [u8; DATA_BUFFER_SZ] = [0u8; DATA_BUFFER_SZ];
            if let Some(encoded_len) = opt.encode(&mut buf) {
                log::info!("opts/save: {}={} ({:x}={:?})", 
                          opt.name(), opt.value(), opt.key().value(), &buf[..encoded_len]);
                self.save_key_retries(opt.key().value(), &buf[..encoded_len], 2)?;
            }
        }
        let mut buf: [u8; DATA_BUFFER_SZ] = [0u8; DATA_BUFFER_SZ];
        if let Some(encoded_len) = opts.page().encode(&mut buf) {
            self.save_key(DEFAULT_PAGE_KEY, &buf[..encoded_len])?;
        }
        Ok(())
    }

    fn load_options<O: Options>(&mut self, opts: &mut O) -> Result<(), Self::Error> {
        for opt in opts.all_mut() {
            let mut buf: [u8; DATA_BUFFER_SZ] = [0u8; DATA_BUFFER_SZ];
            if let Some(len) = self.load_key(opt.key().value(), &mut buf)? {
                opt.decode(&buf[..len]);
                log::info!("opts/load: {}={} ({:x}={:?})", 
                          opt.name(), opt.value(), opt.key().value(), &buf[..len]);
            }
        }
        let mut buf: [u8; DATA_BUFFER_SZ] = [0u8; DATA_BUFFER_SZ];
        if let Some(len) = self.load_key(DEFAULT_PAGE_KEY, &mut buf)? {
            opts.page_mut().decode(&buf[..len]);
        }
        Ok(())
    }
}
