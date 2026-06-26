#[doc = "Register `channel_en` reader"]
pub type R = crate::R<CHANNEL_EN_SPEC>;
#[doc = "Register `channel_en` writer"]
pub type W = crate::W<CHANNEL_EN_SPEC>;
#[doc = "Field `ch0` writer - ch0 field"]
pub type CH0_W<'a, REG> = crate::BitWriter<'a, REG>;
#[doc = "Field `ch1` writer - ch1 field"]
pub type CH1_W<'a, REG> = crate::BitWriter<'a, REG>;
#[doc = "Field `ch2` writer - ch2 field"]
pub type CH2_W<'a, REG> = crate::BitWriter<'a, REG>;
#[doc = "Field `ch3` writer - ch3 field"]
pub type CH3_W<'a, REG> = crate::BitWriter<'a, REG>;
impl W {
    #[doc = "Bit 0 - ch0 field"]
    #[inline(always)]
    pub fn ch0(&mut self) -> CH0_W<'_, CHANNEL_EN_SPEC> {
        CH0_W::new(self, 0)
    }
    #[doc = "Bit 1 - ch1 field"]
    #[inline(always)]
    pub fn ch1(&mut self) -> CH1_W<'_, CHANNEL_EN_SPEC> {
        CH1_W::new(self, 1)
    }
    #[doc = "Bit 2 - ch2 field"]
    #[inline(always)]
    pub fn ch2(&mut self) -> CH2_W<'_, CHANNEL_EN_SPEC> {
        CH2_W::new(self, 2)
    }
    #[doc = "Bit 3 - ch3 field"]
    #[inline(always)]
    pub fn ch3(&mut self) -> CH3_W<'_, CHANNEL_EN_SPEC> {
        CH3_W::new(self, 3)
    }
}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`channel_en::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`channel_en::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct CHANNEL_EN_SPEC;
impl crate::RegisterSpec for CHANNEL_EN_SPEC {
    type Ux = u8;
}
#[doc = "`read()` method returns [`channel_en::R`](R) reader structure"]
impl crate::Readable for CHANNEL_EN_SPEC {}
#[doc = "`write(|w| ..)` method takes [`channel_en::W`](W) writer structure"]
impl crate::Writable for CHANNEL_EN_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets channel_en to value 0"]
impl crate::Resettable for CHANNEL_EN_SPEC {}
