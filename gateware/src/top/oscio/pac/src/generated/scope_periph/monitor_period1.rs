#[doc = "Register `monitor_period1` reader"]
pub type R = crate::R<MONITOR_PERIOD1_SPEC>;
#[doc = "Register `monitor_period1` writer"]
pub type W = crate::W<MONITOR_PERIOD1_SPEC>;
#[doc = "Field `period` reader - period field"]
pub type PERIOD_R = crate::FieldReader<u32>;
impl R {
    #[doc = "Bits 0:23 - period field"]
    #[inline(always)]
    pub fn period(&self) -> PERIOD_R {
        PERIOD_R::new(self.bits & 0x00ff_ffff)
    }
}
impl W {}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`monitor_period1::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`monitor_period1::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct MONITOR_PERIOD1_SPEC;
impl crate::RegisterSpec for MONITOR_PERIOD1_SPEC {
    type Ux = u32;
}
#[doc = "`read()` method returns [`monitor_period1::R`](R) reader structure"]
impl crate::Readable for MONITOR_PERIOD1_SPEC {}
#[doc = "`write(|w| ..)` method takes [`monitor_period1::W`](W) writer structure"]
impl crate::Writable for MONITOR_PERIOD1_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets monitor_period1 to value 0"]
impl crate::Resettable for MONITOR_PERIOD1_SPEC {}
