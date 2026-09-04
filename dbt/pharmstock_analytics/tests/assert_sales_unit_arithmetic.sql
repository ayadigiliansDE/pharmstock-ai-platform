select *
from {{ ref('fct_daily_sales_demand') }}
where requested_units <> fulfilled_units + lost_units
   or requested_units < 0
   or fulfilled_units < 0
   or lost_units < 0
   or fulfillment_rate < 0
   or fulfillment_rate > 1
