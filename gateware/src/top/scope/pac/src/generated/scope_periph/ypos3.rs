#[doc = "Register `ypos3` reader"]
pub type R = crate::R<YPOS3_SPEC>;
#[doc = "Register `ypos3` writer"]
pub type W = crate::W<YPOS3_SPEC>;
#[doc = "Field `ypos` writer - ypos field"]
pub type YPOS_W<'a, REG> = crate::FieldWriter<'a, REG, 16, u16>;
impl W {
    #[doc = "Bits 0:15 - ypos field"]
    #[inline(always)]
    pub fn ypos(&mut self) -> YPOS_W<'_, YPOS3_SPEC> {
        YPOS_W::new(self, 0)
    }
}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`ypos3::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`ypos3::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct YPOS3_SPEC;
impl crate::RegisterSpec for YPOS3_SPEC {
    type Ux = u16;
}
#[doc = "`read()` method returns [`ypos3::R`](R) reader structure"]
impl crate::Readable for YPOS3_SPEC {}
#[doc = "`write(|w| ..)` method takes [`ypos3::W`](W) writer structure"]
impl crate::Writable for YPOS3_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets ypos3 to value 0"]
impl crate::Resettable for YPOS3_SPEC {}
