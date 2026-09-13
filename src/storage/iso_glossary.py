"""
Business vocabulary for ISO 20022 element short names.

The vendored XSDs carry no `xs:documentation`, so a schema outline can tell a
BA where `Cdtr/Nm` sits and how long it may be, but not that it is the
beneficiary's name. This glossary supplies that business layer: a label, a
plain-English definition and the operational terms a payments or trade team
would search for, keyed on the ISO 20022 abbreviation.

It is deliberately small and hand-authored — it covers the elements the demo
messages actually use. Anything outside it still resolves structurally through
the schema index; the answer simply carries no business definition, which the
citation makes explicit rather than inviting the model to invent one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class GlossaryEntry:
    """Business meaning of one ISO 20022 element short name."""

    name: str
    label: str
    definition: str
    aliases: tuple[str, ...] = field(default=())


def _e(name: str, label: str, definition: str, *aliases: str) -> GlossaryEntry:
    return GlossaryEntry(name=name, label=label, definition=definition, aliases=aliases)


_ENTRIES: tuple[GlossaryEntry, ...] = (
    # ── Message and group level ────────────────────────────────────────────
    _e("Document", "Message root",
       "Outermost element of every ISO 20022 message; its namespace states the "
       "exact message type and version."),
    _e("GrpHdr", "Group Header",
       "Batch-level details that apply to every transaction in the message: "
       "identifier, creation timestamp, totals and the initiating party.",
       "header", "batch header"),
    _e("MsgId", "Message Identification",
       "Sender's unique reference for this message. Used for duplicate "
       "detection and for tracing an instruction through operations.",
       "message id", "message reference"),
    _e("CreDtTm", "Creation Date Time",
       "Date and time the sender created the message, in ISO 8601 form. Not "
       "the execution date — a late CreDtTm does not delay settlement.",
       "creation date", "timestamp"),
    _e("NbOfTxs", "Number Of Transactions",
       "Count of individual transactions in the message or payment block. "
       "Receiving banks reconcile it against the transactions present and "
       "reject the batch on a mismatch.",
       "transaction count"),
    _e("CtrlSum", "Control Sum",
       "Sum of all instructed amounts, used as a batch checksum. A mismatch "
       "fails the whole file, not the individual payment.",
       "control total", "batch total"),
    _e("InitgPty", "Initiating Party",
       "Party that created the instruction — often a corporate treasury or a "
       "payment factory acting for the debtor.",
       "initiator"),

    # ── Payment instruction level ──────────────────────────────────────────
    _e("PmtInf", "Payment Information",
       "A block of payments that share a debit account, execution date and "
       "payment method.",
       "payment block"),
    _e("PmtInfId", "Payment Information Identification",
       "Sender's reference for one payment block; appears on the debit "
       "advice and on customer statements.",
       "batch reference"),
    _e("PmtMtd", "Payment Method",
       "How the payment is to be made: TRF (credit transfer), TRA (transfer "
       "advice) or CHK (cheque).",
       "payment type"),
    _e("ReqdExctnDt", "Requested Execution Date",
       "Date the debtor asks its bank to debit the account and release the "
       "payment. Drives value dating and cut-off handling.",
       "execution date", "value date"),
    _e("CdtTrfTxInf", "Credit Transfer Transaction Information",
       "One individual credit transfer inside a payment block.",
       "transaction", "payment line"),
    _e("PmtId", "Payment Identification",
       "Identifiers for a single transaction — the instruction, end-to-end "
       "and (interbank) transaction references.",
       "payment reference"),
    _e("InstrId", "Instruction Identification",
       "Reference assigned by the instructing party for the receiving bank; "
       "point-to-point only and not carried onwards.",
       "instruction reference"),
    _e("EndToEndId", "End To End Identification",
       "Reference supplied by the debtor that must travel unchanged to the "
       "creditor. It is the reference used in payment investigations.",
       "end to end reference", "e2e"),
    _e("UETR", "Unique End-to-end Transaction Reference",
       "UUID v4 that identifies a payment across the whole SWIFT chain; "
       "mandatory for CBPR+ and the key to gpi tracking.",
       "tracker reference", "gpi reference"),
    _e("InstdAmt", "Instructed Amount",
       "Amount the debtor instructed, in the currency instructed, before any "
       "FX conversion or charges.",
       "payment amount", "amount"),
    _e("EqvtAmt", "Equivalent Amount",
       "Amount expressed in a different currency from the debit account, "
       "where the bank performs the conversion."),
    _e("IntrBkSttlmAmt", "Interbank Settlement Amount",
       "Amount actually settled between the two financial institutions — the "
       "figure the clearing system moves.",
       "settlement amount"),
    _e("IntrBkSttlmDt", "Interbank Settlement Date",
       "Value date on which the interbank leg settles.",
       "settlement date"),
    _e("ChrgBr", "Charge Bearer",
       "Who pays the charges: DEBT (debtor), CRED (creditor), SHAR (shared) "
       "or SLEV (following the service level). Wrong values cause short "
       "payments and reconciliation breaks.",
       "charges", "charge bearer"),
    _e("Purp", "Purpose",
       "Why the payment is made, as a code or proprietary value. Used for "
       "regulatory reporting in several markets.",
       "payment purpose"),
    _e("RmtInf", "Remittance Information",
       "What the payment pays for, either free text (Ustrd) or structured "
       "invoice references (Strd). Truncation here breaks the creditor's "
       "auto-reconciliation.",
       "remittance", "narrative", "invoice reference"),
    _e("Ustrd", "Unstructured Remittance Information",
       "Free-text remittance narrative, 140 characters per occurrence."),
    _e("Strd", "Structured Remittance Information",
       "Machine-readable remittance detail — referred document, amounts and "
       "creditor reference."),

    # ── Parties and accounts ───────────────────────────────────────────────
    _e("Dbtr", "Debtor",
       "Party whose account is debited — the payer.",
       "payer", "ordering customer"),
    _e("DbtrAcct", "Debtor Account",
       "Account debited for the payment.",
       "debit account", "ordering account"),
    _e("DbtrAgt", "Debtor Agent",
       "Bank holding the debtor's account — the sending bank.",
       "sending bank", "ordering institution"),
    _e("Cdtr", "Creditor",
       "Party receiving the funds — the beneficiary.",
       "beneficiary", "payee"),
    _e("CdtrAcct", "Creditor Account",
       "Account credited with the funds.",
       "beneficiary account"),
    _e("CdtrAgt", "Creditor Agent",
       "Bank holding the creditor's account — the receiving bank.",
       "beneficiary bank", "receiving bank"),
    _e("UltmtDbtr", "Ultimate Debtor",
       "Party on whose behalf the debtor pays, where it differs from the "
       "account holder."),
    _e("UltmtCdtr", "Ultimate Creditor",
       "Final beneficiary, where it differs from the account owner."),
    _e("Nm", "Name",
       "Name of a party. Sanctions screening runs on this field, so "
       "truncation or abbreviation causes false hits and payment delays.",
       "party name"),
    _e("PstlAdr", "Postal Address",
       "Party address. Structured address components became mandatory for "
       "CBPR+; unstructured address lines are being retired.",
       "address"),
    _e("AdrLine", "Address Line",
       "Unstructured address text, being phased out in favour of structured "
       "components such as TwnNm and Ctry."),
    _e("TwnNm", "Town Name", "Town or city of a party's address.", "city"),
    _e("Ctry", "Country",
       "ISO 3166 two-letter country code of a party or account."),
    _e("IBAN", "International Bank Account Number",
       "Standard international account identifier. Preferred over "
       "proprietary account numbers wherever the market supports it.",
       "account number"),
    _e("Othr", "Other Identification",
       "Proprietary identifier used where an IBAN or BIC is unavailable — "
       "for example a UK sort code and account number pair."),
    _e("BICFI", "Business Identifier Code",
       "BIC of a financial institution (8 or 11 characters). Named BIC in "
       "earlier versions, renamed BICFI from pain.001.001.09 onwards.",
       "bic", "swift code", "swift bic"),
    _e("ClrSysMmbId", "Clearing System Member Identification",
       "National clearing identifier of a bank, such as a UK sort code or a "
       "US routing number.",
       "sort code", "routing number"),
    _e("Ccy", "Currency",
       "ISO 4217 currency code. Carried as an attribute on amount elements.",
       "currency"),

    # ── Cash management (camt) ─────────────────────────────────────────────
    _e("BkToCstmrStmt", "Bank To Customer Statement",
       "camt.053 message body: statements the account servicer sends to the "
       "account owner."),
    _e("Stmt", "Statement",
       "One account statement covering a period, with balances and entries."),
    _e("Acct", "Account", "Account the statement or transaction relates to."),
    _e("Bal", "Balance",
       "Balance of the account at a point in the statement — opening "
       "(OPBD), closing (CLBD), available (CLAV) and others.",
       "balance"),
    _e("Ntry", "Entry",
       "One booked movement on the account — the statement line a "
       "reconciliation team works from.",
       "statement line", "transaction entry"),
    _e("Amt", "Amount",
       "Monetary amount, with its currency in the Ccy attribute."),
    _e("CdtDbtInd", "Credit Debit Indicator",
       "Whether the entry is a credit (CRDT) or a debit (DBIT).",
       "credit debit"),
    _e("Sts", "Status",
       "Status of an entry or transaction — booked (BOOK), pending (PDNG) "
       "or provisional information (INFO)."),
    _e("BookgDt", "Booking Date",
       "Date the entry was booked to the account."),
    _e("ValDt", "Value Date",
       "Date the entry affects the available balance for interest purposes."),

    # ── Trade finance (tsrv / tsmt) ────────────────────────────────────────
    _e("UdrtkgIssncNtfctn", "Undertaking Issuance Notification",
       "tsrv.001 message body: notification that a demand guarantee or "
       "standby letter of credit has been issued — the MX equivalent of "
       "MT 760.",
       "guarantee issuance"),
    _e("Udrtkg", "Undertaking",
       "The guarantee or standby letter of credit itself: applicant, "
       "beneficiary, amount, expiry and terms.",
       "guarantee", "standby lc", "bond"),
    _e("UdrtkgTp", "Undertaking Type",
       "Kind of undertaking — DGAR (demand guarantee), STBY (standby letter "
       "of credit), SURE (surety) and others.",
       "guarantee type"),
    _e("Aplcnt", "Applicant",
       "Party that asks its bank to issue the undertaking — normally the "
       "buyer or contractor.",
       "applicant"),
    _e("Issr", "Issuer",
       "Bank that issues the undertaking and carries the payment obligation.",
       "issuing bank"),
    _e("Bnfcry", "Beneficiary",
       "Party entitled to demand payment under the undertaking.",
       "beneficiary"),
    _e("AdvsgPty", "Advising Party",
       "Bank that passes the undertaking to the beneficiary without taking on "
       "the obligation.",
       "advising bank"),
    _e("UdrtkgAmt", "Undertaking Amount",
       "Maximum amount payable under the undertaking, with its currency and "
       "any tolerance.",
       "guarantee amount"),
    _e("XpryDt", "Expiry Date",
       "Date after which no demand may be presented. Driving date for the "
       "trade operations diary.",
       "expiry"),
    _e("XpryTerms", "Expiry Terms",
       "How the undertaking expires — a fixed date, on an event, or open "
       "ended."),
    _e("GovncRulesAndLaw", "Governing Rules And Law",
       "Rules the undertaking is issued under (URDG 758, ISP98, UCP 600) and "
       "the governing jurisdiction."),
    _e("UdrtkgTermsAndCndtns", "Undertaking Terms And Conditions",
       "Narrative terms of the guarantee, including presentation and demand "
       "requirements."),
    _e("BaselnAmdmntRqst", "Baseline Amendment Request",
       "tsmt.011 message body: request to amend an established trade "
       "services baseline."),
)

_BY_NAME: dict[str, GlossaryEntry] = {e.name.lower(): e for e in _ENTRIES}


def lookup(name: str) -> Optional[GlossaryEntry]:
    """Glossary entry for an element short name, or None if not covered."""
    return _BY_NAME.get((name or "").strip().lstrip("@").lower())


def entries() -> tuple[GlossaryEntry, ...]:
    """Every glossary entry, in authoring order."""
    return _ENTRIES


def search_terms(name: str) -> tuple[str, ...]:
    """Business terms that should match an element short name in a search."""
    entry = lookup(name)
    if entry is None:
        return ()
    return (entry.label.lower(), *entry.aliases)
