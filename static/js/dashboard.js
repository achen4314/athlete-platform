/**
 * 运动员平台 — 仪表盘 JS
 * 数字递增动画
 */
(function() {
  'use strict';

  /**
   * 数字动画：从 0 递增到目标值
   */
  function animateNumber(el, target, decimals, duration) {
    decimals = (decimals !== undefined) ? decimals : 1;
    duration = duration || 1200;

    var start = performance.now();

    function step(timestamp) {
      var elapsed = timestamp - start;
      var progress = Math.min(elapsed / duration, 1.0);

      var eased = 1 - Math.pow(1 - progress, 3);
      var current = target * eased;

      el.textContent = current.toFixed(decimals);
      el.classList.add('counting');

      if (progress < 1) {
        requestAnimationFrame(step);
      } else {
        el.classList.remove('counting');
      }
    }

    requestAnimationFrame(step);
  }

  /* ========== 执行动画 ========== */
  var metrics = [
    { id: 'metricVo2',     value: 58.5, decimals: 1 },
    { id: 'metricBodyFat', value: 10.2, decimals: 1 },
    { id: 'metricRHR',     value: 52,   decimals: 0 },
    { id: 'metricWeight',  value: 73.4, decimals: 1 }
  ];

  metrics.forEach(function(m) {
    var el = document.getElementById(m.id);
    if (!el) return;

    // 检查 data-value 属性（后端可传入真实数据）
    var dataVal = el.getAttribute('data-value');
    if (dataVal !== null && dataVal !== '') {
      m.value = parseFloat(dataVal);
    }

    // 如果页面已渲染真实数值（非 -- 占位符），使用真实值
    var currentText = el.textContent.trim();
    if (currentText !== '--' && !isNaN(parseFloat(currentText))) {
      m.value = parseFloat(currentText);
    }

    var delay = el.closest('.stagger-1') ? 100 :
                el.closest('.stagger-2') ? 200 :
                el.closest('.stagger-3') ? 300 :
                el.closest('.stagger-4') ? 400 : 0;

    setTimeout(function() {
      animateNumber(el, m.value, m.decimals, 1200);
    }, delay);
  });

})();
