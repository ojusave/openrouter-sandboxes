import unittest
from totals import invoice_total

class ShippingAcceptance(unittest.TestCase):
    def test_empty_with_shipping(self):
        self.assertEqual(invoice_total([], shipping_cents=99), 99)
    def test_default(self):
        self.assertEqual(invoice_total([{"unit_price_cents": 3, "quantity": 4}]), 12)
    def test_large_shipping(self):
        self.assertEqual(invoice_total([], shipping_cents=9007199254740993), 9007199254740993)
    def test_negative_shipping(self):
        with self.assertRaises(ValueError):
            invoice_total([], shipping_cents=-1)

if __name__ == "__main__":
    unittest.main()
