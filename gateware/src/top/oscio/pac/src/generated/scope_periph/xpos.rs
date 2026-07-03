#[doc = "Register `xpos` reader"]
pub type R = crate::R<XPOS_SPEC>;
#[doc = "Register `xpos` writer"]
pub type W = crate::W<XPOS_SPEC>;
#[doc = "Field `xpos` writer - xpos field"]
pub type XPOS_W<'a, REG> = crate::FieldWriter<'a, REG, 16, u16>;
impl W {
    #[doc = "Bits 0:15 - xpos field"]
    #[inline(always)]
    pub fn xpos(&mut self) -> XPOS_W<'_, XPOS_SPEC> {
        XPOS_W::new(self, 0)
    }
}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`xpos::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`xpos::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct XPOS_SPEC;
impl crate::RegisterSpec for XPOS_SPEC {
    type Ux = u16;
}
#[doc = "`read()` method returns [`xpos::R`](R) reader structure"]
impl crate::Readable for XPOS_SPEC {}
#[doc = "`write(|w| ..)` method takes [`xpos::W`](W) writer structure"]
impl crate::Writable for XPOS_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets xpos to value 0"]
impl crate::Resettable for XPOS_SPEC {}
