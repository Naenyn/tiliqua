//! Zero-initialized storage for state constructed once before interrupts.
use core::{mem::MaybeUninit,ops::{Deref,DerefMut}};
pub struct StartupState<T> {initialized:bool,state:MaybeUninit<T>}
impl<T> StartupState<T> {
    pub const fn new()->Self {Self {initialized:false,state:MaybeUninit::uninit()}}
    pub fn initialize(&mut self,value:T) {
        assert!(!self.initialized,"state already initialized");
        self.state.write(value);self.initialized=true;
    }
}
impl<T> Deref for StartupState<T> {
    type Target=T;
    fn deref(&self)->&T {
        assert!(self.initialized,"state not initialized");
        // initialize writes the entire value before publishing this flag.
        unsafe {self.state.assume_init_ref()}
    }
}
impl<T> DerefMut for StartupState<T> {
    fn deref_mut(&mut self)->&mut T {
        assert!(self.initialized,"state not initialized");
        unsafe {self.state.assume_init_mut()}
    }
}
impl<T> Drop for StartupState<T> {
    fn drop(&mut self) {if self.initialized {unsafe {self.state.assume_init_drop();}}}
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn initialization_preserves_all_fields_and_supports_mutation() {
        let mut s=StartupState::<([u16;128],&str,u8)>::new();s.initialize(([11u16;128],"STOPPED",4u8));
        assert_eq!(s.0,[11;128]);s.0[127]=29;assert_eq!(s.0[127],29);assert_eq!(s.1,"STOPPED");assert_eq!(s.2,4);
    }
    #[test] fn initialized_value_is_dropped_once() {
        use std::{rc::Rc,cell::Cell};
        struct Count(Rc<Cell<u8>>);
        impl Drop for Count {fn drop(&mut self){self.0.set(self.0.get()+1);}}
        let count=Rc::new(Cell::new(0));
        {let mut s=StartupState::<Count>::new();s.initialize(Count(count.clone()));}
        assert_eq!(count.get(),1);
        drop(StartupState::<Count>::new());assert_eq!(count.get(),1);
    }
    #[test] #[should_panic(expected="state not initialized")]
    fn read_before_initialization_is_rejected() {let s=StartupState::<u8>::new();let _=*s;}
    #[test] #[should_panic(expected="state not initialized")]
    fn mutate_before_initialization_is_rejected() {let mut s=StartupState::<u8>::new();*s=1;}
    #[test] #[should_panic(expected="state already initialized")]
    fn double_initialization_is_rejected() {let mut s=StartupState::<u8>::new();s.initialize(1u8);s.initialize(2);}
}
