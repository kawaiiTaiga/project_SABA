#pragma once
#include "tool.h"

// Common emitter interface for pushing observations to the outside world (/events).
struct IObservationEmitter {
  virtual ~IObservationEmitter() {}
  virtual void emit(const ObservationBuilder& ob) = 0;
};

// Global emitter registration
void set_global_emitter(IObservationEmitter* e);
IObservationEmitter* get_global_emitter();
