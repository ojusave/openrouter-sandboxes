import unittest
from totals import invoice_total

class InvoiceTests(unittest.TestCase):
    def test_quantity(self):
        self.assertEqual(invoice_total([{"unit_price_cents": 125, "quantity": 3}]), 375)

    def test_empty(self):
        self.assertEqual(invoice_total([]), 0)

if __name__ == "__main__":
    unittest.main()
