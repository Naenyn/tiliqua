#[doc = "Register `intensity` reader"]
pub type R = crate::R<INTENSITY_SPEC>;
#[doc = "Register `intensity` writer"]
pub type W = crate::W<INTENSITY_SPEC>;
#[doc = "Field `intensity` writer - intensity field"]
pub type INTENSITY_W<'a, REG> = crate::FieldWriter<'a, REG, 8>;
impl W {
    #[doc = "Bits 0:7 - intensity field"]
    #[inline(always)]
    pub fn intensity(&mut self) -> INTENSITY_W<'_, INTENSITY_SPEC> {
        INTENSITY_W::new(self, 0)
    }
}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`intensity::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`intensity::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct INTENSITY_SPEC;
impl crate::RegisterSpec for INTENSITY_SPEC {
    type Ux = u8;
}
#[doc = "`read()` method returns [`intensity::R`](R) reader structure"]
impl crate::Readable for INTENSITY_SPEC {}
#[doc = "`write(|w| ..)` method takes [`intensity::W`](W) writer structure"]
impl crate::Writable for INTENSITY_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets intensity to value 0"]
impl crate::Resettable for INTENSITY_SPEC {}
