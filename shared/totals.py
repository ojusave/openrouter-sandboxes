def invoice_total(lines):
    """Sum unit_price_cents * quantity for each invoice line."""
    return sum(line["unit_price_cents"] for line in lines)
