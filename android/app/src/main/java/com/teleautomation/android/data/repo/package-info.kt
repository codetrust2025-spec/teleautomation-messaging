/**
 * `data.repo` — repositories that own networking and persistence sources.
 *
 * Repositories return the uniform `NetworkResult<T>` type and are the only callers
 * of the API services and the WebSocket/voice/push clients.
 *
 * This file exists to materialize the package directory in the base layout.
 */
package com.teleautomation.android.data.repo
