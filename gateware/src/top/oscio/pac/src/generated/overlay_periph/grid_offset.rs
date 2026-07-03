#[doc = "Register `grid_offset` reader"]
pub type R = crate::R<GRID_OFFSET_SPEC>;
#[doc = "Register `grid_offset` writer"]
pub type W = crate::W<GRID_OFFSET_SPEC>;
#[doc = "Field `offset_x` writer - offset_x field"]
pub type OFFSET_X_W<'a, REG> = crate::FieldWriter<'a, REG, 12, u16>;
#[doc = "Field `offset_y` writer - offset_y field"]
pub type OFFSET_Y_W<'a, REG> = crate::FieldWriter<'a, REG, 12, u16>;
impl W {
    #[doc = "Bits 0:11 - offset_x field"]
    #[inline(always)]
    pub fn offset_x(&mut self) -> OFFSET_X_W<'_, GRID_OFFSET_SPEC> {
        OFFSET_X_W::new(self, 0)
    }
    #[doc = "Bits 12:23 - offset_y field"]
    #[inline(always)]
    pub fn offset_y(&mut self) -> OFFSET_Y_W<'_, GRID_OFFSET_SPEC> {
        OFFSET_Y_W::new(self, 12)
    }
}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`grid_offset::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`grid_offset::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct GRID_OFFSET_SPEC;
impl crate::RegisterSpec for GRID_OFFSET_SPEC {
    type Ux = u32;
}
#[doc = "`read()` method returns [`grid_offset::R`](R) reader structure"]
impl crate::Readable for GRID_OFFSET_SPEC {}
#[doc = "`write(|w| ..)` method takes [`grid_offset::W`](W) writer structure"]
impl crate::Writable for GRID_OFFSET_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets grid_offset to value 0"]
impl crate::Resettable for GRID_OFFSET_SPEC {}
