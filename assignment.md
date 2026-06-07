# Take-Home Assignment: Remittance Advice Deduction Classification Pipeline

## Background

UNFI (United Natural Foods, Inc.) is one of the largest wholesale food distributors in North America. When UNFI pays a supplier/vendor, they issue a **Remittance Advice (RA)** — a financial document that lists which invoices are being settled and for how much.

In practice, UNFI frequently pays *less* than the original invoice amount. The shortfall on each line item is called a **deduction**. Deductions come in multiple types — some are legitimate fees, some are disputable claims, and some require the vendor to provide backup documentation to resolve. Correctly identifying the *type* of each deduction is the first and most critical step for a vendor to manage their receivables effectively.

Your task is to build a pipeline that automates this identification.

---

## What You Are Given

1. **A set of documents** — provided as attachments. One of them is a UNFI remittance advice. The others are unrelated documents that arrived alongside it (treat them as noise).

2. **A UNFI deduction pattern reference document** — a reference guide describing how UNFI's deduction types are typically identified. This document captures the business logic in human-readable form. It is your job to translate it into a working system.

---

## The Task

Build a pipeline that takes the provided document set as input and produces a structured classification of every deduction line item in the remittance advice.

Specifically, your pipeline should:

1. **Identify** the remittance advice from the document set
2. **Extract** structured line items from it (invoice number, amount, description, etc.)
3. **Analyze** the data and the pattern reference to propose a set of deduction categories — justify why you drew the boundaries where you did
4. **Classify** each line item into one of your proposed categories

The form of the pipeline is your choice — a script, a CLI tool, a REST API, or anything else you think is appropriate. Justify your choice briefly.

### Note
Assume one type of document will not be exactly same, The contents might be same but the structure of the document might differ. 

---

## Constraints

None. Use any language, framework, or tooling you prefer. If you use an LLM anywhere in your pipeline, explain *where*, *why*, and what you would replace it with if the API were unavailable.

---

## Submission

Submit your code along with whatever you feel best communicates your thinking. There is no prescribed format — a README, a design note, inline comments, a short document, or a combination. If we cannot understand your reasoning from the submission alone, that is the gap we will ask about in the follow-up conversation.

---

*Attachments: [RA PDF] [Noise documents] [UNFI deduction pattern reference]*
 
