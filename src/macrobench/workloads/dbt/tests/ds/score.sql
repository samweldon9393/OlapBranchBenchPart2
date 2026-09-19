{{ config(tags=['ds_pipeline']) }}

{% call check('score') %}
SELECT score >= {{ var('threshold') }} AND features = '{{ var('features') }}' AS ok FROM {{ ref('ds_metrics') }}
{% endcall %}
