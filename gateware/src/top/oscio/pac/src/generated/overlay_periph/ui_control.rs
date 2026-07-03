#[doc = "Register `ui_control` reader"]
pub type R = crate::R<UI_CONTROL_SPEC>;
#[doc = "Register `ui_control` writer"]
pub type W = crate::W<UI_CONTROL_SPEC>;
#[doc = "Field `menu_enable` writer - menu_enable field"]
pub type MENU_ENABLE_W<'a, REG> = crate::BitWriter<'a, REG>;
#[doc = "Field `menu_transparent` writer - menu_transparent field"]
pub type MENU_TRANSPARENT_W<'a, REG> = crate::BitWriter<'a, REG>;
#[doc = "Field `rotation` writer - rotation field"]
pub type ROTATION_W<'a, REG> = crate::FieldWriter<'a, REG, 2>;
impl W {
    #[doc = "Bit 0 - menu_enable field"]
    #[inline(always)]
    pub fn menu_enable(&mut self) -> MENU_ENABLE_W<'_, UI_CONTROL_SPEC> {
        MENU_ENABLE_W::new(self, 0)
    }
    #[doc = "Bit 1 - menu_transparent field"]
    #[inline(always)]
    pub fn menu_transparent(&mut self) -> MENU_TRANSPARENT_W<'_, UI_CONTROL_SPEC> {
        MENU_TRANSPARENT_W::new(self, 1)
    }
    #[doc = "Bits 2:3 - rotation field"]
    #[inline(always)]
    pub fn rotation(&mut self) -> ROTATION_W<'_, UI_CONTROL_SPEC> {
        ROTATION_W::new(self, 2)
    }
}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`ui_control::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`ui_control::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct UI_CONTROL_SPEC;
impl crate::RegisterSpec for UI_CONTROL_SPEC {
    type Ux = u8;
}
#[doc = "`read()` method returns [`ui_control::R`](R) reader structure"]
impl crate::Readable for UI_CONTROL_SPEC {}
#[doc = "`write(|w| ..)` method takes [`ui_control::W`](W) writer structure"]
impl crate::Writable for UI_CONTROL_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets ui_control to value 0"]
impl crate::Resettable for UI_CONTROL_SPEC {}
