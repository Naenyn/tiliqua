#[doc = "Register `debug_ctl` reader"]
pub type R = crate::R<DEBUG_CTL_SPEC>;
#[doc = "Register `debug_ctl` writer"]
pub type W = crate::W<DEBUG_CTL_SPEC>;
#[doc = "Field `test_render` writer - test_render field"]
pub type TEST_RENDER_W<'a, REG> = crate::BitWriter<'a, REG>;
impl W {
    #[doc = "Bit 0 - test_render field"]
    #[inline(always)]
    pub fn test_render(&mut self) -> TEST_RENDER_W<'_, DEBUG_CTL_SPEC> {
        TEST_RENDER_W::new(self, 0)
    }
}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`debug_ctl::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`debug_ctl::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct DEBUG_CTL_SPEC;
impl crate::RegisterSpec for DEBUG_CTL_SPEC {
    type Ux = u8;
}
#[doc = "`read()` method returns [`debug_ctl::R`](R) reader structure"]
impl crate::Readable for DEBUG_CTL_SPEC {}
#[doc = "`write(|w| ..)` method takes [`debug_ctl::W`](W) writer structure"]
impl crate::Writable for DEBUG_CTL_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets debug_ctl to value 0"]
impl crate::Resettable for DEBUG_CTL_SPEC {}
