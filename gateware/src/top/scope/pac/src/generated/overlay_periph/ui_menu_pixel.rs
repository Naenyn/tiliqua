#[doc = "Register `ui_menu_pixel` reader"]
pub type R = crate::R<UI_MENU_PIXEL_SPEC>;
#[doc = "Register `ui_menu_pixel` writer"]
pub type W = crate::W<UI_MENU_PIXEL_SPEC>;
#[doc = "Field `pixel` writer - pixel field"]
pub type PIXEL_W<'a, REG> = crate::FieldWriter<'a, REG, 8>;
impl W {
    #[doc = "Bits 0:7 - pixel field"]
    #[inline(always)]
    pub fn pixel(&mut self) -> PIXEL_W<'_, UI_MENU_PIXEL_SPEC> {
        PIXEL_W::new(self, 0)
    }
}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`ui_menu_pixel::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`ui_menu_pixel::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct UI_MENU_PIXEL_SPEC;
impl crate::RegisterSpec for UI_MENU_PIXEL_SPEC {
    type Ux = u8;
}
#[doc = "`read()` method returns [`ui_menu_pixel::R`](R) reader structure"]
impl crate::Readable for UI_MENU_PIXEL_SPEC {}
#[doc = "`write(|w| ..)` method takes [`ui_menu_pixel::W`](W) writer structure"]
impl crate::Writable for UI_MENU_PIXEL_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets ui_menu_pixel to value 0"]
impl crate::Resettable for UI_MENU_PIXEL_SPEC {}
