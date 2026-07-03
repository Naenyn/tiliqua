#[doc = "Register `debug_probe` reader"]
pub type R = crate::R<DEBUG_PROBE_SPEC>;
#[doc = "Register `debug_probe` writer"]
pub type W = crate::W<DEBUG_PROBE_SPEC>;
#[doc = "Field `in_x` reader - in_x field"]
pub type IN_X_R = crate::FieldReader<u16>;
#[doc = "Field `in_y0` reader - in_y0 field"]
pub type IN_Y0_R = crate::FieldReader<u16>;
impl R {
    #[doc = "Bits 0:15 - in_x field"]
    #[inline(always)]
    pub fn in_x(&self) -> IN_X_R {
        IN_X_R::new((self.bits & 0xffff) as u16)
    }
    #[doc = "Bits 16:31 - in_y0 field"]
    #[inline(always)]
    pub fn in_y0(&self) -> IN_Y0_R {
        IN_Y0_R::new(((self.bits >> 16) & 0xffff) as u16)
    }
}
impl W {}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`debug_probe::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`debug_probe::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct DEBUG_PROBE_SPEC;
impl crate::RegisterSpec for DEBUG_PROBE_SPEC {
    type Ux = u32;
}
#[doc = "`read()` method returns [`debug_probe::R`](R) reader structure"]
impl crate::Readable for DEBUG_PROBE_SPEC {}
#[doc = "`write(|w| ..)` method takes [`debug_probe::W`](W) writer structure"]
impl crate::Writable for DEBUG_PROBE_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets debug_probe to value 0"]
impl crate::Resettable for DEBUG_PROBE_SPEC {}
