#[doc = "Register `debug_status` reader"]
pub type R = crate::R<DEBUG_STATUS_SPEC>;
#[doc = "Register `debug_status` writer"]
pub type W = crate::W<DEBUG_STATUS_SPEC>;
#[doc = "Field `fsm` reader - fsm field"]
pub type FSM_R = crate::FieldReader;
#[doc = "Field `capturing` reader - capturing field"]
pub type CAPTURING_R = crate::BitReader;
#[doc = "Field `rendering` reader - rendering field"]
pub type RENDERING_R = crate::BitReader;
#[doc = "Field `sample_valid` reader - sample_valid field"]
pub type SAMPLE_VALID_R = crate::BitReader;
#[doc = "Field `in_plot` reader - in_plot field"]
pub type IN_PLOT_R = crate::BitReader;
#[doc = "Field `at_end` reader - at_end field"]
pub type AT_END_R = crate::BitReader;
#[doc = "Field `sweeping` reader - sweeping field"]
pub type SWEEPING_R = crate::BitReader;
#[doc = "Field `has_col` reader - has_col field"]
pub type HAS_COL_R = crate::BitReader;
#[doc = "Field `sweep_end` reader - sweep_end field"]
pub type SWEEP_END_R = crate::BitReader;
#[doc = "Field `renderer_busy` reader - renderer_busy field"]
pub type RENDERER_BUSY_R = crate::BitReader;
#[doc = "Field `renderer_done` reader - renderer_done field"]
pub type RENDERER_DONE_R = crate::BitReader;
#[doc = "Field `test_mode` reader - test_mode field"]
pub type TEST_MODE_R = crate::BitReader;
#[doc = "Field `soc_en` reader - soc_en field"]
pub type SOC_EN_R = crate::BitReader;
impl R {
    #[doc = "Bits 0:1 - fsm field"]
    #[inline(always)]
    pub fn fsm(&self) -> FSM_R {
        FSM_R::new((self.bits & 3) as u8)
    }
    #[doc = "Bit 2 - capturing field"]
    #[inline(always)]
    pub fn capturing(&self) -> CAPTURING_R {
        CAPTURING_R::new(((self.bits >> 2) & 1) != 0)
    }
    #[doc = "Bit 3 - rendering field"]
    #[inline(always)]
    pub fn rendering(&self) -> RENDERING_R {
        RENDERING_R::new(((self.bits >> 3) & 1) != 0)
    }
    #[doc = "Bit 4 - sample_valid field"]
    #[inline(always)]
    pub fn sample_valid(&self) -> SAMPLE_VALID_R {
        SAMPLE_VALID_R::new(((self.bits >> 4) & 1) != 0)
    }
    #[doc = "Bit 5 - in_plot field"]
    #[inline(always)]
    pub fn in_plot(&self) -> IN_PLOT_R {
        IN_PLOT_R::new(((self.bits >> 5) & 1) != 0)
    }
    #[doc = "Bit 6 - at_end field"]
    #[inline(always)]
    pub fn at_end(&self) -> AT_END_R {
        AT_END_R::new(((self.bits >> 6) & 1) != 0)
    }
    #[doc = "Bit 7 - sweeping field"]
    #[inline(always)]
    pub fn sweeping(&self) -> SWEEPING_R {
        SWEEPING_R::new(((self.bits >> 7) & 1) != 0)
    }
    #[doc = "Bit 8 - has_col field"]
    #[inline(always)]
    pub fn has_col(&self) -> HAS_COL_R {
        HAS_COL_R::new(((self.bits >> 8) & 1) != 0)
    }
    #[doc = "Bit 9 - sweep_end field"]
    #[inline(always)]
    pub fn sweep_end(&self) -> SWEEP_END_R {
        SWEEP_END_R::new(((self.bits >> 9) & 1) != 0)
    }
    #[doc = "Bit 10 - renderer_busy field"]
    #[inline(always)]
    pub fn renderer_busy(&self) -> RENDERER_BUSY_R {
        RENDERER_BUSY_R::new(((self.bits >> 10) & 1) != 0)
    }
    #[doc = "Bit 11 - renderer_done field"]
    #[inline(always)]
    pub fn renderer_done(&self) -> RENDERER_DONE_R {
        RENDERER_DONE_R::new(((self.bits >> 11) & 1) != 0)
    }
    #[doc = "Bit 12 - test_mode field"]
    #[inline(always)]
    pub fn test_mode(&self) -> TEST_MODE_R {
        TEST_MODE_R::new(((self.bits >> 12) & 1) != 0)
    }
    #[doc = "Bit 13 - soc_en field"]
    #[inline(always)]
    pub fn soc_en(&self) -> SOC_EN_R {
        SOC_EN_R::new(((self.bits >> 13) & 1) != 0)
    }
}
impl W {}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`debug_status::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`debug_status::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct DEBUG_STATUS_SPEC;
impl crate::RegisterSpec for DEBUG_STATUS_SPEC {
    type Ux = u16;
}
#[doc = "`read()` method returns [`debug_status::R`](R) reader structure"]
impl crate::Readable for DEBUG_STATUS_SPEC {}
#[doc = "`write(|w| ..)` method takes [`debug_status::W`](W) writer structure"]
impl crate::Writable for DEBUG_STATUS_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets debug_status to value 0"]
impl crate::Resettable for DEBUG_STATUS_SPEC {}
