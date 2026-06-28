#[doc = "Register `debug_count` reader"]
pub type R = crate::R<DEBUG_COUNT_SPEC>;
#[doc = "Register `debug_count` writer"]
pub type W = crate::W<DEBUG_COUNT_SPEC>;
#[doc = "Field `capture_done` reader - capture_done field"]
pub type CAPTURE_DONE_R = crate::FieldReader;
#[doc = "Field `render_done` reader - render_done field"]
pub type RENDER_DONE_R = crate::FieldReader;
#[doc = "Field `col_writes` reader - col_writes field"]
pub type COL_WRITES_R = crate::FieldReader;
#[doc = "Field `flush_drops` reader - flush_drops field"]
pub type FLUSH_DROPS_R = crate::FieldReader;
impl R {
    #[doc = "Bits 0:7 - capture_done field"]
    #[inline(always)]
    pub fn capture_done(&self) -> CAPTURE_DONE_R {
        CAPTURE_DONE_R::new((self.bits & 0xff) as u8)
    }
    #[doc = "Bits 8:15 - render_done field"]
    #[inline(always)]
    pub fn render_done(&self) -> RENDER_DONE_R {
        RENDER_DONE_R::new(((self.bits >> 8) & 0xff) as u8)
    }
    #[doc = "Bits 16:23 - col_writes field"]
    #[inline(always)]
    pub fn col_writes(&self) -> COL_WRITES_R {
        COL_WRITES_R::new(((self.bits >> 16) & 0xff) as u8)
    }
    #[doc = "Bits 24:31 - flush_drops field"]
    #[inline(always)]
    pub fn flush_drops(&self) -> FLUSH_DROPS_R {
        FLUSH_DROPS_R::new(((self.bits >> 24) & 0xff) as u8)
    }
}
impl W {}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`debug_count::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`debug_count::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct DEBUG_COUNT_SPEC;
impl crate::RegisterSpec for DEBUG_COUNT_SPEC {
    type Ux = u32;
}
#[doc = "`read()` method returns [`debug_count::R`](R) reader structure"]
impl crate::Readable for DEBUG_COUNT_SPEC {}
#[doc = "`write(|w| ..)` method takes [`debug_count::W`](W) writer structure"]
impl crate::Writable for DEBUG_COUNT_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets debug_count to value 0"]
impl crate::Resettable for DEBUG_COUNT_SPEC {}
