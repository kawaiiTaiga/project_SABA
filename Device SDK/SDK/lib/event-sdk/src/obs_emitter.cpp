#include "obs_emitter.h"
#include <stddef.h>

static IObservationEmitter* g_emitter = nullptr;

void set_global_emitter(IObservationEmitter* e){ g_emitter = e; }
IObservationEmitter* get_global_emitter(){ return g_emitter; }
