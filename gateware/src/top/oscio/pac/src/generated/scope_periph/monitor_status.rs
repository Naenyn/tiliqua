#[doc = "Register `monitor_status` reader"]
pub type R = crate::R<MONITOR_STATUS_SPEC>;
#[doc = "Register `monitor_status` writer"]
pub type W = crate::W<MONITOR_STATUS_SPEC>;
#[doc = "Field `valid` reader - valid field"]
pub type VALID_R = crate::FieldReader;
#[doc = "Field `rapid` reader - rapid field"]
pub type RAPID_R = crate::FieldReader;
impl R {
    #[doc = "Bits 0:3 - valid field"]
    #[inline(always)]
    pub fn valid(&self) -> VALID_R {
        VALID_R::new(self.bits & 0x0f)
    }
    #[doc = "Bits 4:7 - rapid field"]
    #[inline(always)]
    pub fn rapid(&self) -> RAPID_R {
        RAPID_R::new((self.bits >> 4) & 0x0f)
    }
}
impl W {}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`monitor_status::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`monitor_status::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct MONITOR_STATUS_SPEC;
impl crate::RegisterSpec for MONITOR_STATUS_SPEC {
    type Ux = u8;
}
#[doc = "`read()` method returns [`monitor_status::R`](R) reader structure"]
impl crate::Readable for MONITOR_STATUS_SPEC {}
#[doc = "`write(|w| ..)` method takes [`monitor_status::W`](W) writer structure"]
impl crate::Writable for MONITOR_STATUS_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets monitor_status to value 0"]
impl crate::Resettable for MONITOR_STATUS_SPEC {}
