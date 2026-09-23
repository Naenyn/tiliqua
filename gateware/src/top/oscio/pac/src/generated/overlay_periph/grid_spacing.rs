#[doc = "Register `grid_spacing` reader"]
pub type R = crate::R<GRID_SPACING_SPEC>;
#[doc = "Register `grid_spacing` writer"]
pub type W = crate::W<GRID_SPACING_SPEC>;
#[doc = "Field `spacing_x` writer - spacing_x field"]
pub type SPACING_X_W<'a, REG> = crate::FieldWriter<'a, REG, 8>;
#[doc = "Field `spacing_y` writer - spacing_y field"]
pub type SPACING_Y_W<'a, REG> = crate::FieldWriter<'a, REG, 8>;
impl W {
    #[doc = "Bits 0:7 - spacing_x field"]
    #[inline(always)]
    pub fn spacing_x(&mut self) -> SPACING_X_W<'_, GRID_SPACING_SPEC> {
        SPACING_X_W::new(self, 0)
    }
    #[doc = "Bits 8:15 - spacing_y field"]
    #[inline(always)]
    pub fn spacing_y(&mut self) -> SPACING_Y_W<'_, GRID_SPACING_SPEC> {
        SPACING_Y_W::new(self, 8)
    }
}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`grid_spacing::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`grid_spacing::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct GRID_SPACING_SPEC;
impl crate::RegisterSpec for GRID_SPACING_SPEC {
    type Ux = u16;
}
#[doc = "`read()` method returns [`grid_spacing::R`](R) reader structure"]
impl crate::Readable for GRID_SPACING_SPEC {}
#[doc = "`write(|w| ..)` method takes [`grid_spacing::W`](W) writer structure"]
impl crate::Writable for GRID_SPACING_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets grid_spacing to value 0"]
impl crate::Resettable for GRID_SPACING_SPEC {}
