/// A tiny base trait.
pub trait Base {
    fn log(&self, message: &str) -> String;
}

pub struct OrderError;
