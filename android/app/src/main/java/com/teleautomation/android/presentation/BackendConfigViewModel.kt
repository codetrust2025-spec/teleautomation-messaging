package com.teleautomation.android.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.teleautomation.android.data.repo.BackendConfigRepository
import com.teleautomation.android.data.repo.InvalidBackendConfigException
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Immutable UI state for the Backend configuration screen (R23.6).
 *
 * @property persistedUrl the Backend base URL currently stored, or `null` when none
 *   has been configured yet. Reflects what the repository has persisted.
 * @property input the current text in the URL field (what the Operator is editing).
 * @property errorMessage a validation/error message to show inline next to the
 *   field, or `null` when there is no error.
 * @property successMessage a confirmation message to show after a successful save,
 *   or `null` when there is nothing to confirm.
 * @property isSaving whether a save is currently in flight (used to disable the
 *   save control and avoid duplicate submissions).
 */
data class BackendConfigUiState(
    val persistedUrl: String? = null,
    val input: String = "",
    val errorMessage: String? = null,
    val successMessage: String? = null,
    val isSaving: Boolean = false,
)

/**
 * Presentation-layer ViewModel for [com.teleautomation.android.ui.config.BackendConfigScreen].
 *
 * Exposes [uiState] as a [StateFlow] the screen observes, and delegates all
 * persistence/validation to [BackendConfigRepository]. The composable contains no
 * business logic: it only renders [uiState] and forwards user intents
 * ([onInputChanged], [onSave]) here (MVVM).
 *
 * On save the ViewModel calls [BackendConfigRepository.setBaseUrl]; a
 * [Result.failure] carrying an [InvalidBackendConfigException] surfaces the
 * validation reason inline via [BackendConfigUiState.errorMessage], while a
 * [Result.success] surfaces a confirmation and reflects the newly persisted value
 * (R23.6).
 */
@HiltViewModel
class BackendConfigViewModel @Inject constructor(
    private val repository: BackendConfigRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(BackendConfigUiState())
    val uiState: StateFlow<BackendConfigUiState> = _uiState.asStateFlow()

    /**
     * Tracks whether the Operator has started editing the field. Until then we keep
     * the input mirrored to the persisted value as it loads/changes; once the user
     * edits, we stop overwriting their in-progress text.
     */
    private var userHasEdited = false

    init {
        viewModelScope.launch {
            repository.config.collect { config ->
                val persisted = config?.baseUrl
                _uiState.update { current ->
                    current.copy(
                        persistedUrl = persisted,
                        // Pre-fill the field with the persisted value until the
                        // Operator begins editing.
                        input = if (userHasEdited) current.input else persisted.orEmpty(),
                    )
                }
            }
        }
    }

    /** Records the latest field text and clears any stale error/success messages. */
    fun onInputChanged(value: String) {
        userHasEdited = true
        _uiState.update { current ->
            current.copy(
                input = value,
                errorMessage = null,
                successMessage = null,
            )
        }
    }

    /**
     * Validates and persists the current [BackendConfigUiState.input] via the
     * repository. On success surfaces a confirmation and lets the persisted value
     * reflect through the [repository] flow; on failure surfaces the validation
     * reason inline without persisting anything (R23.6).
     */
    fun onSave() {
        val raw = _uiState.value.input
        _uiState.update { it.copy(isSaving = true, errorMessage = null, successMessage = null) }

        viewModelScope.launch {
            val result = repository.setBaseUrl(raw)
            result.fold(
                onSuccess = {
                    // The persisted value flows back through repository.config; the
                    // field is no longer "dirty" relative to what is stored.
                    userHasEdited = false
                    _uiState.update {
                        it.copy(
                            isSaving = false,
                            errorMessage = null,
                            successMessage = "Backend URL saved.",
                        )
                    }
                },
                onFailure = { throwable ->
                    _uiState.update {
                        it.copy(
                            isSaving = false,
                            successMessage = null,
                            errorMessage = throwable.message
                                ?: "The Backend URL is invalid.",
                        )
                    }
                },
            )
        }
    }
}
