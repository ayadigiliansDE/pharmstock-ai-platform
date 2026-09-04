select *
from {{ ref('stg7h_demand_attempt') }}
where requested_units != fulfilled_units + lost_units
