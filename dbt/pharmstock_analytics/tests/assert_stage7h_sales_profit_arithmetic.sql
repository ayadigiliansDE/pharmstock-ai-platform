select *
from {{ ref('stg7h_sale_line') }}
where abs(net_sales_egp - cogs_egp - gross_profit_egp) > 0.01
