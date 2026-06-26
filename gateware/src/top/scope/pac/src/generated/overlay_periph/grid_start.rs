#[doc = "Register `grid_start` reader"]
pub type R = crate::R<GRID_START_SPEC>;
#[doc = "Register `grid_start` writer"]
pub type W = crate::W<GRID_START_SPEC>;
#[doc = "Field `start_x` writer - start_x field"]
pub type START_X_W<'a, REG> = crate::FieldWriter<'a, REG, 8>;
#[doc = "Field `start_y` writer - start_y field"]
pub type START_Y_W<'a, REG> = crate::FieldWriter<'a, REG, 8>;
impl W {
    #[doc = "Bits 0:7 - start_x field"]
    #[inline(always)]
    pub fn start_x(&mut self) -> START_X_W<'_, GRID_START_SPEC> {
        START_X_W::new(self, 0)
    }
    #[doc = "Bits 8:15 - start_y field"]
    #[inline(always)]
    pub fn start_y(&mut self) -> START_Y_W<'_, GRID_START_SPEC> {
        START_Y_W::new(self, 8)
    }
}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`grid_start::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`grid_start::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct GRID_START_SPEC;
impl crate::RegisterSpec for GRID_START_SPEC {
    type Ux = u16;
}
#[doc = "`read()` method returns [`grid_start::R`](R) reader structure"]
impl crate::Readable for GRID_START_SPEC {}
#[doc = "`write(|w| ..)` method takes [`grid_start::W`](W) writer structure"]
impl crate::Writable for GRID_START_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets grid_start to value 0"]
impl crate::Resettable for GRID_START_SPEC {}
