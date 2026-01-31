def normalize_crd_class(loan_dt) -> str:
    if loan_dt and str(loan_dt).strip():
        return "CREDIT"
    return "CASH"
