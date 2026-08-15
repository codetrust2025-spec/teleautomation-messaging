package com.teleautomation.android.core

/**
 * Pure, device-independent gate for the Telegram OTP login phone number (R8.1, R8.2).
 *
 * This logic lives in `core` (no Android, OkHttp, or Retrofit dependencies) so it is
 * unit/property testable on the plain JVM. The `TelegramLoginScreen`/OTP ViewModel
 * (tasks plan 10.6) delegate here before deciding whether to invoke the repository's
 * `POST /login/send-otp` call; the call is made only when the result is
 * [PhoneNumberResult.Valid].
 *
 * Backing requirement (R8.1/R8.2): a phone number is valid only when it is a
 * *selected country code* followed by 4 to 15 digits, with no other characters; an
 * empty, malformed, or out-of-range value is rejected with an error and the
 * send-OTP endpoint must NOT be called.
 *
 * Backing property (Property 9): for any phone input composed of a supported country
 * code followed by a digit run, the validator accepts it if and only if the digit
 * count is between 4 and 15 inclusive and all trailing characters are digits; empty,
 * malformed, or out-of-range inputs are rejected.
 *
 * ## "Supported country code" policy
 *
 * A *supported country code* is modelled as a literal dialing prefix — a leading `+`
 * followed by the country calling code digits (E.164 style, e.g. `+1`, `+44`, `+91`).
 * The set of supported codes is supplied by the caller: the OTP screen (task 10.6)
 * passes the country codes restricted to the Backend-supported values, so the gate
 * never accepts a code the Backend cannot service. [DEFAULT_SUPPORTED_COUNTRY_CODES]
 * provides a reasonable default used only when a caller does not supply its own set
 * (e.g. tests).
 *
 * When several supported codes are prefixes of the same input (e.g. `+1` and `+12`),
 * the **longest** matching code is selected so the most specific country wins; the
 * remaining characters are then the national digit run that must be 4–15 ASCII
 * digits. Only ASCII `0`–`9` count as digits (Unicode digit look-alikes are
 * rejected) to match the Backend's E.164 expectations.
 */
object PhoneNumberPolicy {

    /** Minimum number of national digits required after the country code (R8.1). */
    const val MIN_NATIONAL_DIGITS: Int = 4

    /** Maximum number of national digits allowed after the country code (R8.1). */
    const val MAX_NATIONAL_DIGITS: Int = 15

    /**
     * A reasonable default set of supported country calling codes, used only when a
     * caller does not supply its own restricted set. Production callers (the OTP
     * screen, task 10.6) pass the Backend-supported values instead (R8.7).
     */
    val DEFAULT_SUPPORTED_COUNTRY_CODES: Set<String> = setOf(
        "+1",   // North America (US/Canada)
        "+7",   // Russia / Kazakhstan
        "+20",  // Egypt
        "+27",  // South Africa
        "+33",  // France
        "+34",  // Spain
        "+39",  // Italy
        "+44",  // United Kingdom
        "+49",  // Germany
        "+55",  // Brazil
        "+61",  // Australia
        "+62",  // Indonesia
        "+65",  // Singapore
        "+81",  // Japan
        "+86",  // China
        "+91",  // India
        "+92",  // Pakistan
        "+880", // Bangladesh
        "+971", // United Arab Emirates
        "+972", // Israel
    )

    /**
     * Validates a candidate phone number [input] against the supported-country-code
     * set, without any side effects.
     *
     * Returns [PhoneNumberResult.Valid] carrying the normalized E.164 number
     * (`+` + country code digits + national digits) when [input] — after trimming
     * surrounding whitespace — begins with one of [supportedCountryCodes] and is
     * followed by [MIN_NATIONAL_DIGITS]..[MAX_NATIONAL_DIGITS] ASCII digits and
     * nothing else. Otherwise returns [PhoneNumberResult.Invalid] with a
     * human-readable reason; the caller must then NOT invoke `POST /login/send-otp`.
     *
     * @param input the raw phone-number text as entered/assembled by the UI.
     * @param supportedCountryCodes the dialing prefixes the Backend can service;
     *   each must be a leading `+` plus digits. Defaults to
     *   [DEFAULT_SUPPORTED_COUNTRY_CODES].
     * @throws IllegalArgumentException if [supportedCountryCodes] is empty or
     *   contains a malformed code (programming error, not user input).
     */
    fun validate(
        input: String,
        supportedCountryCodes: Set<String> = DEFAULT_SUPPORTED_COUNTRY_CODES,
    ): PhoneNumberResult {
        require(supportedCountryCodes.isNotEmpty()) {
            "At least one supported country code must be provided."
        }
        require(supportedCountryCodes.all(::isWellFormedCode)) {
            "Supported country codes must be a leading '+' followed by ASCII digits."
        }

        val trimmed = input.trim()
        if (trimmed.isEmpty()) {
            return PhoneNumberResult.Invalid("Phone number must not be blank.")
        }
        if (!trimmed.startsWith("+")) {
            return PhoneNumberResult.Invalid(
                "Phone number must begin with a country code, e.g. +1.",
            )
        }

        // Select the most specific (longest) supported code that prefixes the input.
        val countryCode = supportedCountryCodes
            .filter { trimmed.startsWith(it) }
            .maxByOrNull { it.length }
            ?: return PhoneNumberResult.Invalid(
                "Country code is not in the supported list.",
            )

        val national = trimmed.substring(countryCode.length)
        if (national.isEmpty()) {
            return PhoneNumberResult.Invalid(
                "Enter the phone number digits after the country code.",
            )
        }
        if (!national.all(::isAsciiDigit)) {
            return PhoneNumberResult.Invalid(
                "The number may contain only digits after the country code.",
            )
        }
        if (national.length < MIN_NATIONAL_DIGITS || national.length > MAX_NATIONAL_DIGITS) {
            return PhoneNumberResult.Invalid(
                "The number must have $MIN_NATIONAL_DIGITS to $MAX_NATIONAL_DIGITS digits " +
                    "after the country code (was ${national.length}).",
            )
        }

        return PhoneNumberResult.Valid(normalized = countryCode + national)
    }

    /** A supported code is a leading `+` followed by one or more ASCII digits. */
    private fun isWellFormedCode(code: String): Boolean =
        code.length >= 2 && code[0] == '+' && code.drop(1).all(::isAsciiDigit)

    private fun isAsciiDigit(c: Char): Boolean = c in '0'..'9'
}

/** Outcome of gating a phone-number submission via [PhoneNumberPolicy.validate]. */
sealed interface PhoneNumberResult {
    /**
     * The submission is allowed; the caller may invoke `POST /login/send-otp`.
     *
     * @property normalized the canonical E.164 number (`+` + country code +
     *   national digits) safe to send to the Backend.
     */
    data class Valid(val normalized: String) : PhoneNumberResult

    /**
     * The submission is rejected; the caller must NOT invoke the send-OTP endpoint
     * and must surface [reason] to the Operator (R8.2).
     */
    data class Invalid(val reason: String) : PhoneNumberResult
}
