// 渲染进程核心逻辑
const { ipcRenderer } = require('electron');

// 添加错误处理
window.addEventListener('error', (event) => {
  console.error('渲染进程错误:', event.error);
});

window.addEventListener('unhandledrejection', (event) => {
  console.error('渲染进程未处理的Promise拒绝:', event.reason);
});

// 音效播放器类
class SoundPlayer {
    constructor() {
        this.audioContext = null;
        this.sounds = {};
        this.lastPlayedTime = {};
        this.cooldownTime = 100; // 音效冷却时间（毫秒）
        this.initAudioContext();
    }

    initAudioContext() {
        try {
            // 创建音频上下文
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            console.log('音频上下文已初始化');
            
            // 加载所有音效文件
            this.loadSounds();
        } catch (error) {
            console.error('初始化音频上下文失败:', error);
        }
    }

    async loadSounds() {
        // 原有音效 [1-8]
        for (let i = 1; i <= 8; i++) {
            await this.loadSound(`assets/${i}.mp3`, `${i}`);
            await this.loadSound(`assets/${i}.wav`, `${i}_wav`);
        }
        
        // q系列音效 [1-9]
        for (let i = 1; i <= 9; i++) {
            await this.loadSound(`assets/q${i}.mp3`, `q${i}`);
            await this.loadSound(`assets/q${i}.wav`, `q${i}_wav`);
        }
        
        // z系列音效 [1-6]
        for (let i = 1; i <= 6; i++) {
            await this.loadSound(`assets/z${i}.mp3`, `z${i}`);
            await this.loadSound(`assets/z${i}.wav`, `z${i}_wav`);
        }
        
        console.log('所有音效加载完成');
    }

    async loadSound(filePath, soundId) {
        try {
            const response = await fetch(filePath);
            if (!response.ok) {
                console.warn(`音效文件不存在: ${filePath}`);
                return;
            }
            const arrayBuffer = await response.arrayBuffer();
            const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);
            this.sounds[soundId] = audioBuffer;
            console.log(`已加载音效: ${soundId}`);
        } catch (error) {
            console.warn(`加载音效失败 ${filePath}:`, error.message);
        }
    }

    playSound(soundId) {
        if (!this.audioContext || !this.sounds[soundId]) {
            console.error(`音效未加载: ${soundId}`);
            return false;
        }

        // 检查冷却时间，避免重复播放
        const now = Date.now();
        if (this.lastPlayedTime[soundId] && now - this.lastPlayedTime[soundId] < this.cooldownTime) {
            return false;
        }

        try {
            const source = this.audioContext.createBufferSource();
            source.buffer = this.sounds[soundId];
            source.connect(this.audioContext.destination);
            source.start(0);
            
            this.lastPlayedTime[soundId] = now;
            return true;
        } catch (error) {
            console.error(`播放音效失败 ${soundId}:`, error);
            return false;
        }
    }

    playRandomSound() {
        // 优先使用mp3格式，如果没有则使用wav格式
        const soundId = Math.floor(Math.random() * 8) + 1;
        if (this.sounds[`${soundId}`]) {
            return this.playSound(`${soundId}`);
        } else if (this.sounds[`${soundId}_wav`]) {
            return this.playSound(`${soundId}_wav`);
        } else {
            console.warn(`未找到音效: ${soundId}`);
            return false;
        }
    }

    playQSound() {
        // 优先使用mp3格式，如果没有则使用wav格式
        const soundId = Math.floor(Math.random() * 9) + 1;
        if (this.sounds[`q${soundId}`]) {
            return this.playSound(`q${soundId}`);
        } else if (this.sounds[`q${soundId}_wav`]) {
            return this.playSound(`q${soundId}_wav`);
        } else {
            console.warn(`未找到音效: q${soundId}`);
            return false;
        }
    }

    playZSound() {
        // 优先使用mp3格式，如果没有则使用wav格式
        const soundId = Math.floor(Math.random() * 6) + 1;
        if (this.sounds[`z${soundId}`]) {
            return this.playSound(`z${soundId}`);
        } else if (this.sounds[`z${soundId}_wav`]) {
            return this.playSound(`z${soundId}_wav`);
        } else {
            console.warn(`未找到音效: z${soundId}`);
            return false;
        }
    }
}

// 弹窗管理器
class PopupManager {
    constructor() {
        // 初始化DOM元素
        this.initElements();
        
        // 初始化事件监听器
        this.initEventListeners();
        
        // 初始化音效播放器
        this.soundPlayer = new SoundPlayer();
        
        // 初始化状态变量
        this.isSticky = false;
        this.isZZoneBlocked = false;
        this.zStateIsA = true; // true = Red, false = Blue
        
        // 生命周期计时器
        this.lifecycleTimer = null;
        this.LIFECYCLE_SECONDS = 19;
        
        // 冷却指示器计时器
        this.cooldownTimer = null;
        this.cooldownStartTime = null;
        this.COOLDOWN_TIME_MS = 500;
    }

    initElements() {
        // 获取DOM元素
        this.elements = {
            container: document.getElementById('popup-container'),
            topContent: document.getElementById('top-content'),
            bottomMessage: document.getElementById('bottom-message'),
            overlayScrollbar: document.getElementById('overlay-scrollbar'),
            scrollbarThumb: document.getElementById('scrollbar-thumb'),
            zArea: document.getElementById('z-click-area'),
            shield: document.getElementById('interaction-shield'),
            cooldownIndicator: document.getElementById('cooldown-indicator')
        };
        
        // 验证所有元素是否存在
        for (const [key, element] of Object.entries(this.elements)) {
            if (!element) {
                console.error(`Element not found: ${key}`);
            }
        }
        
        // 为了兼容性，保留原有的属性引用
        this.popupContainer = this.elements.container;
        this.topContent = this.elements.topContent;
        this.bottomMessage = this.elements.bottomMessage;
        this.overlayScrollbar = this.elements.overlayScrollbar;
        this.scrollbarThumb = this.elements.scrollbarThumb;
        this.zClickArea = this.elements.zArea;
        this.interactionShield = this.elements.shield;
        this.cooldownIndicator = this.elements.cooldownIndicator;
        
        // 创建冷却进度条
        this.cooldownProgress = document.createElement('div');
        this.cooldownProgress.className = 'progress';
        this.cooldownIndicator.appendChild(this.cooldownProgress);
        
        // 初始化滚动条
        this.initScrollbar();
        console.log('元素初始化完成');
        
        // 初始化时显示滚动条
        this.overlayScrollbar.style.display = 'block';
    }

    initScrollbar() {
    // 初始时隐藏滚动条
    this.overlayScrollbar.style.display = 'none';
    
    let isDragging = false;
    let startY = 0;
    let startScrollTop = 0;

    // 滚动条拖动
    this.scrollbarThumb.addEventListener('mousedown', (e) => {
      isDragging = true;
      startY = e.clientY;
      startScrollTop = this.topContent.scrollTop;
      e.preventDefault();
      e.stopPropagation();
    });

    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      
      const deltaY = e.clientY - startY;
      const thumbHeight = this.scrollbarThumb.offsetHeight;
      const trackHeight = this.overlayScrollbar.offsetHeight;
      const scrollRatio = deltaY / (trackHeight - thumbHeight);
      const maxScroll = this.topContent.scrollHeight - this.topContent.clientHeight;
      
      this.topContent.scrollTop = startScrollTop + (scrollRatio * maxScroll);
      e.preventDefault();
    });

    document.addEventListener('mouseup', () => {
      isDragging = false;
    });

    // 滚动条点击
    this.overlayScrollbar.addEventListener('click', (e) => {
      if (e.target === this.scrollbarThumb) return;
      
      const rect = this.overlayScrollbar.getBoundingClientRect();
      const thumbHeight = this.scrollbarThumb.offsetHeight;
      const clickY = e.clientY - rect.top;
      const scrollRatio = clickY / rect.offsetHeight;
      const maxScroll = this.topContent.scrollHeight - this.topContent.clientHeight;
      
      this.topContent.scrollTop = scrollRatio * maxScroll;
      e.preventDefault();
      e.stopPropagation();
    });

    // 内容滚动时更新滚动条
    this.topContent.addEventListener('scroll', () => {
      this.updateScrollbar();
    });
  }

    updateScrollbar() {
        if (!this.overlayScrollbar) return;
        
        const scrollHeight = this.topContent.scrollHeight;
        const clientHeight = this.topContent.clientHeight;
        const scrollTop = this.topContent.scrollTop;
        
        // 在所有模式下都显示滚动条，如果内容可滚动
        if (scrollHeight <= clientHeight) {
            this.overlayScrollbar.style.display = 'none';
            return;
        }
        
        this.overlayScrollbar.style.display = 'block';
        
        const thumbHeight = Math.max(30, (clientHeight / scrollHeight) * this.overlayScrollbar.offsetHeight);
        const thumbTop = (scrollTop / (scrollHeight - clientHeight)) * (this.overlayScrollbar.offsetHeight - thumbHeight);
        
        this.scrollbarThumb.style.height = `${thumbHeight}px`;
        this.scrollbarThumb.style.top = `${thumbTop}px`;
        
        // 确保滚动条可以拖动
        this.scrollbarThumb.style.cursor = 'pointer';
        this.overlayScrollbar.style.cursor = 'pointer';
    }

    initEventListeners() {
        // Z区点击事件
        this.elements.zArea.addEventListener('click', (e) => {
            this.handleZClick();
        });

        // Q区点击事件
        this.elements.shield.addEventListener('click', (e) => {
            this.handleQClick();
        });

        // 滚轮事件 - 在所有模式下都允许滚动
        this.elements.shield.addEventListener('wheel', (e) => {
            this.elements.topContent.scrollTop += e.deltaY;
            e.preventDefault();
        });
        
        // 添加到popupContainer的滚轮事件，确保在所有模式下都能滚动
        this.elements.container.addEventListener('wheel', (e) => {
            this.elements.topContent.scrollTop += e.deltaY;
            e.preventDefault();
        });
        
        // 添加到topContent的滚轮事件，确保在虚线框内也能滚动
        this.elements.topContent.addEventListener('wheel', (e) => {
            this.elements.topContent.scrollTop += e.deltaY;
            e.preventDefault();
        });
        
        // 添加到document的滚轮事件，确保在任何地方都能滚动
        document.addEventListener('wheel', (e) => {
            // 检查鼠标是否在弹窗区域内
            const rect = this.elements.container.getBoundingClientRect();
            if (e.clientX >= rect.left && e.clientX <= rect.right && 
                e.clientY >= rect.top && e.clientY <= rect.bottom) {
                this.elements.topContent.scrollTop += e.deltaY;
                e.preventDefault();
            }
        });

        // 内容变化时更新滚动条
        this.elements.topContent.addEventListener('input', () => {
            this.updateScrollbar();
        });

        // 复制事件
        this.elements.topContent.addEventListener('copy', () => {
            this.soundPlayer.playRandomSound();
        });
    }

    handleZClick() {
        // --- "快逻辑" ---
        if (this.zStateIsA) {
            this.soundPlayer.playZSound();
        } else {
            this.soundPlayer.playQSound();
        }
        this.elements.zArea.classList.toggle('z-state-b');
        this.zStateIsA = !this.zStateIsA;
        
        // --- "慢逻辑" (异步防抖) ---
        if (this.isZZoneBlocked) return;
        this.isZZoneBlocked = true;
        setTimeout(() => this.performStickyToggleOnly(), 0);
    }

    handleQClick() {
        if (!this.isSticky) {
            this.soundPlayer.playQSound();
            this.slideOut();
            // 发送用户主动关闭窗口的请求
            setTimeout(() => {
                ipcRenderer.send('user-close-popup');
            }, 300); // 等待滑出动画完成
        }
    }

    toggleStickyMode() {
        this.isSticky = !this.isSticky;
        if (this.isSticky) {
            this.stopLifecycle();
            this.popupContainer.classList.add('sticky-mode');
            this.interactionShield.style.display = 'none'; // 隐藏屏蔽层
            this.topContent.setAttribute('contenteditable', 'true'); // 允许编辑
            this.topContent.focus();
            console.log('已激活粘滞模式');
        } else {
            this.startLifecycle();
            this.popupContainer.classList.remove('sticky-mode');
            this.interactionShield.style.display = 'block'; // 显示屏蔽层
            this.topContent.setAttribute('contenteditable', 'false'); // 禁止编辑
            
            // 重置Z区状态
            this.zClickArea.classList.remove('z-state-b');
            this.zStateIsA = true;
            console.log('已退出粘滞模式');
        }
    }

    performStickyToggleOnly() {
        this.toggleStickyMode();
        this.isZZoneBlocked = false; // 解锁
    }

    activateStickyMode() {
        this.isSticky = true;
        this.popupContainer.classList.add('sticky');
        this.interactionShield.style.display = 'none';
        this.topContent.contentEditable = true;
        this.topContent.focus();
        
        // 在便签模式下显示滚动条
        this.overlayScrollbar.style.display = 'block';
        this.updateScrollbar();
        
        // 在粘滞模式下停止冷却指示条
        this.stopCooldownIndicator();
        
        // 启动边框动画
        this.startBorderAnimation();
    }

    deactivateStickyMode() {
        this.isSticky = false;
        this.popupContainer.classList.remove('sticky');
        this.interactionShield.style.display = 'block';
        this.topContent.contentEditable = false;
        this.topContent.blur();
        
        // 退出便签模式时，始终显示滚动条
        this.overlayScrollbar.style.display = 'block';
        this.updateScrollbar();
        
        // 退出粘滞模式时，重新启动冷却指示条
        this.startCooldownIndicator(10000); // 10秒冷却时间
        
        // 停止边框动画
        this.stopBorderAnimation();
        
        // 重置FSM状态
        this.zClickArea.classList.remove('blue');
        this.zClickArea.classList.add('red');
        this.zStateIsA = true;
        
        // 重置锁
        this.isZZoneBlocked = false;
    }

    startBorderAnimation() {
        if (this.borderAnimationInterval) return;
        
        let offset = 0;
        this.borderAnimationInterval = setInterval(() => {
            offset = (offset - 1) % -10;
            this.popupContainer.style.backgroundPosition = `${offset}px 0`;
        }, 51);
    }

    stopBorderAnimation() {
        if (this.borderAnimationInterval) {
            clearInterval(this.borderAnimationInterval);
            this.borderAnimationInterval = null;
        }
    }

    startLifecycle() {
        // 清除之前的计时器
        if (this.lifecycleTimer) {
            clearTimeout(this.lifecycleTimer);
        }
        
        // 设置新的计时器
        this.lifecycleTimer = setTimeout(() => {
            if (!this.isSticky) {
                console.log('生命周期结束，自动关闭弹窗');
                this.slideOut();
            }
        }, this.LIFECYCLE_SECONDS * 1000);
        console.log('生命周期计时器已启动，19秒后自动关闭');
        
        // 启动冷却指示条
        this.startCooldownIndicator(this.LIFECYCLE_SECONDS * 1000);
    }
    
    stopLifecycle() {
        if (this.lifecycleTimer) {
            clearTimeout(this.lifecycleTimer);
            this.lifecycleTimer = null;
        }
    }

    startCooldownIndicator() {
        // 清除之前的计时器
        if (this.cooldownTimer) {
            clearInterval(this.cooldownTimer);
        }
        
        // 记录开始时间
        this.cooldownStartTime = Date.now();
        
        // 显示冷却指示器
        this.elements.cooldownIndicator.style.display = 'block';
        
        // 更新冷却指示器进度
        this.cooldownTimer = setInterval(() => {
            const elapsed = Date.now() - this.cooldownStartTime;
            const progress = Math.min(elapsed / this.COOLDOWN_TIME_MS, 1);
            
            // 更新宽度
            this.elements.cooldownIndicator.style.width = `${(1 - progress) * 100}%`;
            
            // 如果冷却完成，隐藏指示器
            if (progress >= 1) {
                this.stopCooldownIndicator();
            }
        }, 10); // 每10ms更新一次，使动画更流畅
    }
    
    stopCooldownIndicator() {
        if (this.cooldownTimer) {
            clearInterval(this.cooldownTimer);
            this.cooldownTimer = null;
        }
        
        // 隐藏冷却指示器
        this.elements.cooldownIndicator.style.display = 'none';
    }

    slideOut() {
        if (this.isSlidingOut) return;
        
        // 如果在粘滞模式下，不关闭窗口
        if (this.isSticky) {
            console.log('在粘滞模式下，不关闭窗口');
            return;
        }
        
        // 如果尚未初始化完成，不关闭窗口
        if (!this.isInitialized) {
            console.log('尚未初始化完成，不关闭窗口');
            return;
        }
        
        this.isSlidingOut = true;
        
        // 清除所有计时器
        if (this.lifecycleTimer) {
            clearTimeout(this.lifecycleTimer);
        }
        this.stopBorderAnimation();
        this.stopCooldownIndicator(); // 停止冷却指示条
        
        // 添加滑出动画类
        this.elements.container.classList.remove('slide-in');
        this.elements.container.classList.add('slide-out');
        
        // 动画完成后，通知主进程窗口已关闭
        setTimeout(() => {
            console.log('滑出动画完成，发送关闭窗口请求');
            // 发送关闭窗口请求，让主进程决定是否关闭窗口
            ipcRenderer.send('close-popup');
        }, 300);
    }

    slideIn() {
        // 添加滑入动画类
        this.popupContainer.classList.add('slide-in');
        
        // 动画完成后移除类
        setTimeout(() => {
            this.popupContainer.classList.remove('slide-in');
        }, 300);
    }

    updateContent(topText, bottomText) {
        this.topContent.innerText = topText || '';
        this.bottomMessage.innerText = bottomText || '';
        this.updateScrollbar();
        
        // 只有在窗口可见时才启动生命周期计时器
        if (document.visibilityState === 'visible') {
            this.startLifecycle();
        }
    }

    updateBottomText(text) {
        this.bottomMessage.innerText = text;
    }
    
    updateColorMode(colorMode) {
        this.elements.container.className = colorMode === 0 ? 'theme-dark' : 'theme-light';
    }
}

// 初始化应用
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM已加载，开始初始化应用');
    window.popupManager = new PopupManager();
    console.log('PopupManager已创建');
    
    // 接收主进程数据
    ipcRenderer.on('update-popup-content', (event, data) => {
        console.log('收到更新内容请求:', data);
        window.popupManager.updateContent(data.topText, data.bottomText);
    });
    
    // 接收颜色模式更新
    ipcRenderer.on('update-color-mode', (event, colorMode) => {
        console.log('收到颜色模式更新:', colorMode);
        window.popupManager.updateColorMode(colorMode);
    });
    
    // 接收底部文本更新
    ipcRenderer.on('update-bottom-text', (event, text) => {
        console.log('收到底部文本更新:', text);
        window.popupManager.updateBottomText(text);
    });
    
    // 接收音效播放请求
    ipcRenderer.on('play-sound', (event, soundType) => {
        console.log('收到音效播放请求:', soundType);
        if (soundType === 'random') {
            window.popupManager.soundPlayer.playRandomSound();
        } else if (soundType === 'q') {
            window.popupManager.soundPlayer.playQSound();
        } else if (soundType === 'z') {
            window.popupManager.soundPlayer.playZSound();
        }
    });
    
    // 接收关闭弹窗请求
    ipcRenderer.on('close-popup', () => {
        console.log('收到关闭弹窗请求');
        window.popupManager.slideOut();
    });
    
    // 添加键盘快捷键监听
    document.addEventListener('keydown', (event) => {
        // Ctrl+Shift+C 手动触发剪贴板检查
        if (event.ctrlKey && event.shiftKey && event.key === 'C') {
            console.log('手动触发剪贴板检查');
            ipcRenderer.send('check-clipboard');
        }
    });
    
    // 通知主进程渲染进程已准备就绪
    console.log('发送renderer-ready信号');
    ipcRenderer.send('renderer-ready');
});