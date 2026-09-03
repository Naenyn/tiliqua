#[doc = "Register `trace_reset` reader"]
pub type R = crate::R<TRACE_RESET_SPEC>;
#[doc = "Register `trace_reset` writer"]
pub type W = crate::W<TRACE_RESET_SPEC>;
#[doc = "Field `reset` writer - reset field"]
pub type RESET_W<'a, REG> = crate::BitWriter<'a, REG>;
impl W {
    #[doc = "Bit 0 - reset field"]
    #[inline(always)]
    pub fn reset(&mut self) -> RESET_W<'_, TRACE_RESET_SPEC> {
        RESET_W::new(self, 0)
    }
}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`trace_reset::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`trace_reset::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct TRACE_RESET_SPEC;
impl crate::RegisterSpec for TRACE_RESET_SPEC {
    type Ux = u8;
}
#[doc = "`read()` method returns [`trace_reset::R`](R) reader structure"]
impl crate::Readable for TRACE_RESET_SPEC {}
#[doc = "`write(|w| ..)` method takes [`trace_reset::W`](W) writer structure"]
impl crate::Writable for TRACE_RESET_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets trace_reset to value 0"]
impl crate::Resettable for TRACE_RESET_SPEC {}
