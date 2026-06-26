#[doc = "Register `pixels_per_volt` reader"]
pub type R = crate::R<PIXELS_PER_VOLT_SPEC>;
#[doc = "Register `pixels_per_volt` writer"]
pub type W = crate::W<PIXELS_PER_VOLT_SPEC>;
#[doc = "Field `pixels_per_volt` reader - pixels_per_volt field"]
pub type PIXELS_PER_VOLT_R = crate::FieldReader<u16>;
impl R {
    #[doc = "Bits 0:15 - pixels_per_volt field"]
    #[inline(always)]
    pub fn pixels_per_volt(&self) -> PIXELS_PER_VOLT_R {
        PIXELS_PER_VOLT_R::new(self.bits)
    }
}
impl W {}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`pixels_per_volt::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`pixels_per_volt::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct PIXELS_PER_VOLT_SPEC;
impl crate::RegisterSpec for PIXELS_PER_VOLT_SPEC {
    type Ux = u16;
}
#[doc = "`read()` method returns [`pixels_per_volt::R`](R) reader structure"]
impl crate::Readable for PIXELS_PER_VOLT_SPEC {}
#[doc = "`write(|w| ..)` method takes [`pixels_per_volt::W`](W) writer structure"]
impl crate::Writable for PIXELS_PER_VOLT_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets pixels_per_volt to value 0"]
impl crate::Resettable for PIXELS_PER_VOLT_SPEC {}
