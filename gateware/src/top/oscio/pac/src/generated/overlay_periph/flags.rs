#[doc = "Register `flags` reader"]
pub type R = crate::R<FLAGS_SPEC>;
#[doc = "Register `flags` writer"]
pub type W = crate::W<FLAGS_SPEC>;
#[doc = "Field `grid_style` writer - grid_style field"]
pub type GRID_STYLE_W<'a, REG> = crate::FieldWriter<'a, REG, 2>;
#[doc = "Field `grid_pixel` writer - grid_pixel field"]
pub type GRID_PIXEL_W<'a, REG> = crate::FieldWriter<'a, REG, 8>;
impl W {
    #[doc = "Bits 0:1 - grid_style field"]
    #[inline(always)]
    pub fn grid_style(&mut self) -> GRID_STYLE_W<'_, FLAGS_SPEC> {
        GRID_STYLE_W::new(self, 0)
    }
    #[doc = "Bits 2:9 - grid_pixel field"]
    #[inline(always)]
    pub fn grid_pixel(&mut self) -> GRID_PIXEL_W<'_, FLAGS_SPEC> {
        GRID_PIXEL_W::new(self, 2)
    }
}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`flags::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`flags::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct FLAGS_SPEC;
impl crate::RegisterSpec for FLAGS_SPEC {
    type Ux = u16;
}
#[doc = "`read()` method returns [`flags::R`](R) reader structure"]
impl crate::Readable for FLAGS_SPEC {}
#[doc = "`write(|w| ..)` method takes [`flags::W`](W) writer structure"]
impl crate::Writable for FLAGS_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets flags to value 0"]
impl crate::Resettable for FLAGS_SPEC {}
