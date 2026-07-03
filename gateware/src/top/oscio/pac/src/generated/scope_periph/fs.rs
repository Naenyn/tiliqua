#[doc = "Register `fs` reader"]
pub type R = crate::R<FS_SPEC>;
#[doc = "Register `fs` writer"]
pub type W = crate::W<FS_SPEC>;
#[doc = "Field `fs` reader - fs field"]
pub type FS_R = crate::FieldReader<u32>;
impl R {
    #[doc = "Bits 0:31 - fs field"]
    #[inline(always)]
    pub fn fs(&self) -> FS_R {
        FS_R::new(self.bits)
    }
}
impl W {}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`fs::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`fs::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct FS_SPEC;
impl crate::RegisterSpec for FS_SPEC {
    type Ux = u32;
}
#[doc = "`read()` method returns [`fs::R`](R) reader structure"]
impl crate::Readable for FS_SPEC {}
#[doc = "`write(|w| ..)` method takes [`fs::W`](W) writer structure"]
impl crate::Writable for FS_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets fs to value 0"]
impl crate::Resettable for FS_SPEC {}
