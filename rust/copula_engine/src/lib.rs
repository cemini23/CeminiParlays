//! `_copula_engine`: the Rust numeric tail for `ceminiparlays.copula`.
//!
//! Exported to Python as `ceminiparlays._copula_engine`. The RNG stays in
//! Python; every draw is passed in already materialised.

pub mod engine;
pub mod math;

#[cfg(feature = "python")]
mod python;
