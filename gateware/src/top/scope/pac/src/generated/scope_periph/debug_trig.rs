#[doc = "Register `debug_trig` reader"]
pub type R = crate::R<DEBUG_TRIG_SPEC>;
#[doc = "Register `debug_trig` writer"]
pub type W = crate::W<DEBUG_TRIG_SPEC>;
#[doc = "Field `trig_edges` reader - trig_edges field"]
pub type TRIG_EDGES_R = crate::FieldReader;
#[doc = "Field `ramp_restarts` reader - ramp_restarts field"]
pub type RAMP_RESTARTS_R = crate::FieldReader;
#[doc = "Field `pen_lifts` reader - pen_lifts field"]
pub type PEN_LIFTS_R = crate::FieldReader;
#[doc = "Field `end_reached` reader - end_reached field"]
pub type END_REACHED_R = crate::FieldReader;
impl R {
    #[doc = "Bits 0:7 - trig_edges field"]
    #[inline(always)]
    pub fn trig_edges(&self) -> TRIG_EDGES_R {
        TRIG_EDGES_R::new((self.bits & 0xff) as u8)
    }
    #[doc = "Bits 8:15 - ramp_restarts field"]
    #[inline(always)]
    pub fn ramp_restarts(&self) -> RAMP_RESTARTS_R {
        RAMP_RESTARTS_R::new(((self.bits >> 8) & 0xff) as u8)
    }
    #[doc = "Bits 16:23 - pen_lifts field"]
    #[inline(always)]
    pub fn pen_lifts(&self) -> PEN_LIFTS_R {
        PEN_LIFTS_R::new(((self.bits >> 16) & 0xff) as u8)
    }
    #[doc = "Bits 24:31 - end_reached field"]
    #[inline(always)]
    pub fn end_reached(&self) -> END_REACHED_R {
        END_REACHED_R::new(((self.bits >> 24) & 0xff) as u8)
    }
}
impl W {}
#[doc = "A CSR register. Parameters ---------- fields : :class:`dict` or :class:`list` or :class:`Field` Collection of register fields. If ``None`` (default), a dict is populated from Python :term:`variable annotations <python:variable annotations>`. ``fields`` is used to create a :class:`FieldActionMap`, :class:`FieldActionArray`, or :class:`FieldAction`, depending on its type (dict, list, or Field). Interface attributes -------------------- element : :class:`Element` Interface between this register and a CSR bus primitive. Attributes ---------- field : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Collection of field instances. f : :class:`FieldActionMap` or :class:`FieldActionArray` or :class:`FieldAction` Shorthand for :attr:`Register.field`. Raises ------ :exc:`TypeError` If ``fields`` is neither ``None``, a :class:`dict`, a :class:`list`, or a :class:`Field`. :exc:`ValueError` If ``fields`` is not ``None`` and at least one variable annotation is a :class:`Field`. :exc:`ValueError` If ``element.access`` is not readable and at least one field is readable. :exc:`ValueError` If ``element.access`` is not writable and at least one field is writable.\n\nYou can [`read`](crate::Reg::read) this register and get [`debug_trig::R`](R). You can [`reset`](crate::Reg::reset), [`write`](crate::Reg::write), [`write_with_zero`](crate::Reg::write_with_zero) this register using [`debug_trig::W`](W). You can also [`modify`](crate::Reg::modify) this register. See [API](https://docs.rs/svd2rust/#read--modify--write-api)."]
pub struct DEBUG_TRIG_SPEC;
impl crate::RegisterSpec for DEBUG_TRIG_SPEC {
    type Ux = u32;
}
#[doc = "`read()` method returns [`debug_trig::R`](R) reader structure"]
impl crate::Readable for DEBUG_TRIG_SPEC {}
#[doc = "`write(|w| ..)` method takes [`debug_trig::W`](W) writer structure"]
impl crate::Writable for DEBUG_TRIG_SPEC {
    type Safety = crate::Unsafe;
}
#[doc = "`reset()` method sets debug_trig to value 0"]
impl crate::Resettable for DEBUG_TRIG_SPEC {}
