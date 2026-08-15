package com.teleautomation.android.core

/**
 * Pure, device-independent view state derived from a [NetworkResult] for a single
 * view (R25.1–R25.5).
 *
 * A [NetworkResult] describes *what the Backend call did* (it is in flight,
 * succeeded with data, succeeded with no items, or failed). A [ViewState] describes
 * *what the view should render* as a consequence. Keeping the two separate lets the
 * mapping live in `core` (no Android/Compose dependencies) so it is unit/property
 * testable on the plain JVM, while the Compose `TransientStateHost` only has to
 * render whichever [ViewState] it is handed.
 *
 * Backing property (Property 30): for any [NetworkResult], the selected state is
 * [Loading] for [NetworkResult.Loading]; [EmptyState] for a successful zero-item
 * result ([NetworkResult.Empty]); [Content] for a non-empty success
 * ([NetworkResult.Success]); and [ErrorWithRetry] for [NetworkResult.Error], in
 * which case the previously displayed data for that view is retained
 * ([ErrorWithRetry.retainedData]).
 */
sealed interface ViewState<out T> {

    /** A Backend request for the view is in progress; show a loading indicator (R25.1). */
    data object Loading : ViewState<Nothing>

    /**
     * The request succeeded but produced no items; show an empty-state message
     * indicating that no data is available (R25.2).
     */
    data object EmptyState : ViewState<Nothing>

    /** The request succeeded with at least one item; show [data] (R25.2 inverse). */
    data class Content<out T>(val data: T) : ViewState<T>

    /**
     * The request failed; show an error message and a retry control while keeping
     * any previously displayed data for the view (R25.4, R25.5).
     *
     * @param kind the single [ErrorKind] assigned by [NetworkErrorClassifier].
     * @param message a human-readable description for the affected view.
     * @param retry re-issues the same operation with the original parameters and
     *   yields a fresh [NetworkResult] (R26.5, R26.6); the Compose retry control is
     *   wired to this closure.
     * @param retainedData the last content displayed for this view before the
     *   failure, or `null` if the view had no content yet. Retaining it lets the
     *   view keep showing stale data behind the error indication (R25.4).
     */
    data class ErrorWithRetry<out T>(
        val kind: ErrorKind,
        val message: String,
        val retry: suspend () -> NetworkResult<T>,
        val retainedData: T?,
    ) : ViewState<T>
}

/**
 * Pure mapping from a [NetworkResult] to the [ViewState] a view should render
 * (R25.1–R25.5, Property 30).
 *
 * This is the single source of truth for transient-state selection. The Compose
 * `TransientStateHost` (UI layer) delegates here so the rendering decision itself
 * carries no Android/Compose dependencies and can be exercised on the plain JVM.
 */
object ViewStateSelector {

    /**
     * Selects the [ViewState] for [result], retaining [previousContent] as the
     * fallback data shown alongside an error.
     *
     * Mapping (total over every [NetworkResult] case, Property 30):
     *  - [NetworkResult.Loading] → [ViewState.Loading] (R25.1).
     *  - [NetworkResult.Empty] (a successful zero-item result) → [ViewState.EmptyState]
     *    (R25.2).
     *  - [NetworkResult.Success] (a non-empty success) → [ViewState.Content] holding
     *    the produced data.
     *  - [NetworkResult.Error] → [ViewState.ErrorWithRetry] carrying the same kind,
     *    message, and retry closure, plus [previousContent] as
     *    [ViewState.ErrorWithRetry.retainedData] so the view keeps the last data it
     *    displayed (R25.4, R25.5).
     *
     * @param result the latest result for the view.
     * @param previousContent the last content the view displayed, or `null` if it
     *   had none. Only consulted for the [NetworkResult.Error] case; it is the data
     *   the view should retain behind the error indication (R25.4).
     */
    fun <T> select(result: NetworkResult<T>, previousContent: T? = null): ViewState<T> =
        when (result) {
            is NetworkResult.Loading -> ViewState.Loading
            is NetworkResult.Empty -> ViewState.EmptyState
            is NetworkResult.Success -> ViewState.Content(result.data)
            is NetworkResult.Error -> ViewState.ErrorWithRetry(
                kind = result.kind,
                message = result.message,
                retry = result.retry,
                retainedData = previousContent,
            )
        }
}
