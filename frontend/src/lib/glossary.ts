/**
 * Plain-English labels, definitions and one-line examples for every metric (FR-7).
 * Keys match backend/src/finxplore/metrics.py.
 */
export const GLOSSARY = {
  revenue: {
    label: "Revenue (sales)",
    definition: "All the money a company brings in from selling its products or services.",
    example: "A lemonade stand that sells 100 cups at $2 has $200 of revenue.",
  },
  gross_profit: {
    label: "Gross profit",
    definition: "Revenue minus the direct cost of making what was sold.",
    example: "If the lemons and cups for those 100 cups cost $80, gross profit is $120.",
  },
  operating_income: {
    label: "Operating income",
    definition: "Profit from the core business after everyday costs like salaries and rent.",
    example: "Pay the stand's helper $50 and operating income drops to $70.",
  },
  net_income: {
    label: "Net income (profit)",
    definition: "What's left after every expense, including interest and taxes. The bottom line.",
    example: "After $10 of taxes, the stand's net income is $60.",
  },
  rnd_expense: {
    label: "Research & development",
    definition: "Money spent inventing or improving products.",
    example: "Testing a new pink-lemonade recipe costs money before it earns any.",
  },
  eps_diluted: {
    label: "Earnings per share",
    definition: "Net income divided by the number of shares, i.e. the profit each share 'owns'.",
    example: "$60 of profit split across 30 shares is $2 per share.",
  },
  shares_diluted: {
    label: "Shares outstanding",
    definition: "How many slices the company's ownership is cut into.",
    example: "If there are 30 shares and you own 3, you own 10% of the company.",
  },
  operating_cash_flow: {
    label: "Operating cash flow",
    definition: "Cash actually coming in from running the business (not just profit on paper).",
    example: "Sales made on credit count as revenue, but only add cash once customers pay.",
  },
  capex: {
    label: "Capital expenditures",
    definition: "Money spent on long-lasting things like buildings, machines and equipment.",
    example: "Buying a $300 juicer that lasts five years.",
  },
  free_cash_flow: {
    label: "Free cash flow",
    definition: "Operating cash flow minus capital expenditures: cash left over to use freely.",
    example: "$100 of operating cash minus a $30 juicer leaves $70 of free cash flow.",
  },
  dividends_paid: {
    label: "Dividends paid",
    definition: "Cash the company paid out to its shareholders.",
    example: "Paying each of 30 shares $1 means $30 of dividends.",
  },
  total_assets: {
    label: "Total assets",
    definition: "Everything the company owns that has value: cash, buildings, inventory and more.",
    example: "The stand, the juicer, the lemons and the cash box together.",
  },
  total_liabilities: {
    label: "Total liabilities",
    definition: "Everything the company owes to others, like loans and unpaid bills.",
    example: "A $200 loan from your parents to buy the stand.",
  },
  stockholders_equity: {
    label: "Shareholders' equity",
    definition: "Assets minus liabilities: the part of the company the owners truly own.",
    example: "$500 of stuff minus a $200 loan leaves $300 of equity.",
  },
  cash: {
    label: "Cash and equivalents",
    definition: "Money in the bank, plus investments that can be turned into cash almost instantly.",
    example: "The $150 sitting in the cash box and the stand's bank account.",
  },
  long_term_debt: {
    label: "Long-term debt",
    definition: "Borrowed money that isn't due for more than a year.",
    example: "A loan you'll pay back over the next three summers.",
  },
} as const satisfies Record<string, { label: string; definition: string; example: string }>;

export type MetricKey = keyof typeof GLOSSARY;
