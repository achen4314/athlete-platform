/**
 * 运动员平台 — 通用 ECharts 图表渲染函数
 * 依赖：echarts CDN
 */
(function(global) {
  'use strict';

  var DEFAULT_COLORS = ['#a0c040', '#c0c060', '#4caf50', '#2196f3', '#ff9800', '#e53935'];
  var DARK_THEME = {
    backgroundColor: '#16213e',
    borderColor: '#0f3460',
    textColor: '#e8e8e8',
    mutedColor: '#606878',
    splitColor: '#1e2d50',
  };

  /**
   * 渲染雷达图
   * @param {string} domId - DOM 容器 ID
   * @param {Array} indicators - [{name: '力量', max: 80}, ...]
   * @param {Array} seriesData - [{name: '张三', value: [60, 55, ...], color: '#a0c040'}, ...]
   */
  global.renderRadarChart = function(domId, indicators, seriesData) {
    var dom = document.getElementById(domId);
    if (!dom || typeof echarts === 'undefined') return null;

    var chart = echarts.init(dom);
    var series = seriesData.map(function(s) {
      return {
        type: 'radar',
        data: [{ value: s.value, name: s.name }],
        areaStyle: { color: (s.color || DEFAULT_COLORS[0]) + '30' },
        lineStyle: { color: s.color || DEFAULT_COLORS[0], width: 2 },
        itemStyle: { color: s.color || DEFAULT_COLORS[0] }
      };
    });

    chart.setOption({
      tooltip: {
        backgroundColor: DARK_THEME.backgroundColor,
        borderColor: DARK_THEME.borderColor,
        textStyle: { color: DARK_THEME.textColor }
      },
      legend: {
        data: seriesData.map(function(s) { return s.name; }),
        textStyle: { color: '#a0a8b8' },
        bottom: 0
      },
      radar: {
        center: ['50%', '48%'],
        radius: '65%',
        indicator: indicators,
        axisName: { color: '#a0a8b8', fontSize: 12 },
        splitArea: {
          areaStyle: { color: ['rgba(160,192,64,0.02)', 'rgba(160,192,64,0.04)'] }
        },
        splitLine: { lineStyle: { color: DARK_THEME.splitColor } },
        axisLine: { lineStyle: { color: DARK_THEME.splitColor } }
      },
      series: series
    });

    window.addEventListener('resize', function() { chart.resize(); });
    return chart;
  };

  /**
   * 渲染柱状图（多系列对比）
   * @param {string} domId
   * @param {Array} categories - x轴分类
   * @param {Array} seriesData - [{name, data, color?}, ...]
   */
  global.renderBarChart = function(domId, categories, seriesData, opts) {
    opts = opts || {};
    var dom = document.getElementById(domId);
    if (!dom || typeof echarts === 'undefined') return null;

    var chart = echarts.init(dom);
    var series = seriesData.map(function(s, idx) {
      return {
        name: s.name,
        type: 'bar',
        data: s.data,
        itemStyle: {
          color: s.color || DEFAULT_COLORS[idx % DEFAULT_COLORS.length],
          borderRadius: [4, 4, 0, 0]
        }
      };
    });

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: DARK_THEME.backgroundColor,
        borderColor: DARK_THEME.borderColor,
        textStyle: { color: DARK_THEME.textColor }
      },
      legend: {
        data: seriesData.map(function(s) { return s.name; }),
        textStyle: { color: '#a0a8b8' },
        top: 0
      },
      grid: {
        left: '3%', right: '4%', bottom: '3%',
        top: opts.legendTop || '40px', containLabel: true
      },
      xAxis: {
        type: 'category',
        data: categories,
        axisLabel: { color: '#a0a8b8', fontSize: 11, rotate: opts.rotate || 20 },
        axisLine: { lineStyle: { color: DARK_THEME.splitColor } }
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: DARK_THEME.mutedColor },
        splitLine: { lineStyle: { color: DARK_THEME.splitColor } }
      },
      series: series
    });

    window.addEventListener('resize', function() { chart.resize(); });
    return chart;
  };

  /**
   * 渲染折线趋势图（含回归线）
   * @param {string} domId
   * @param {Array} dates - 日期标签
   * @param {Array} values - 数值
   * @param {string} unitLabel - y轴单位
   */
  global.renderTrendChart = function(domId, dates, values, unitLabel) {
    var dom = document.getElementById(domId);
    if (!dom || typeof echarts === 'undefined' || values.length < 2) return null;

    var chart = echarts.init(dom);

    // 简单线性回归
    var n = values.length;
    var sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
    for (var i = 0; i < n; i++) {
      sumX += i; sumY += values[i];
      sumXY += i * values[i]; sumX2 += i * i;
    }
    var slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
    var intercept = (sumY - slope * sumX) / n;
    var regValues = [];
    for (var i = 0; i < n; i++) regValues.push(intercept + slope * i);

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        backgroundColor: DARK_THEME.backgroundColor,
        borderColor: DARK_THEME.borderColor,
        textStyle: { color: DARK_THEME.textColor }
      },
      legend: {
        data: ['实测值', '趋势线'],
        textStyle: { color: '#a0a8b8' }, top: 0
      },
      grid: {
        left: '3%', right: '4%', bottom: '3%',
        top: '40px', containLabel: true
      },
      xAxis: {
        type: 'category', data: dates,
        axisLabel: { color: DARK_THEME.mutedColor, fontSize: 10, rotate: 25 },
        axisLine: { lineStyle: { color: DARK_THEME.splitColor } }
      },
      yAxis: {
        type: 'value', name: unitLabel,
        nameTextStyle: { color: DARK_THEME.mutedColor },
        axisLabel: { color: DARK_THEME.mutedColor },
        splitLine: { lineStyle: { color: DARK_THEME.splitColor } }
      },
      series: [
        {
          name: '实测值', type: 'line', data: values, smooth: true,
          lineStyle: { color: '#a0c040', width: 2 },
          itemStyle: { color: '#a0c040' },
          symbol: 'circle', symbolSize: 8
        },
        {
          name: '趋势线', type: 'line', data: regValues,
          lineStyle: { color: '#c0c060', width: 1.5, type: 'dashed' },
          itemStyle: { color: '#c0c060' }, symbol: 'none'
        }
      ]
    });

    window.addEventListener('resize', function() { chart.resize(); });
    return chart;
  };

})(window);
