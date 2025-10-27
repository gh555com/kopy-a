// main.js - Electron主进程
const { app, BrowserWindow, screen, clipboard, ipcMain, globalShortcut } = require('electron');
const path = require('path');
const fs = require('fs');

// 确保app完全初始化后再设置命令行参数
app.whenReady().then(() => {
  // 解决缓存问题和乱码的命令行参数
  app.commandLine.appendSwitch('disable-gpu');
  app.commandLine.appendSwitch('disable-gpu-compositing');
  app.commandLine.appendSwitch('disable-software-rasterizer');
  app.commandLine.appendSwitch('disable-background-timer-throttling');
  app.commandLine.appendSwitch('disable-backgrounding-occluded-windows');
  app.commandLine.appendSwitch('disable-renderer-backgrounding');
  app.commandLine.appendSwitch('disable-features', 'VizDisplayCompositor');
  app.commandLine.appendSwitch('disable-features', 'IsolateOrigins,site-per-process');
  app.commandLine.appendSwitch('disable-site-isolation-trials');
  app.commandLine.appendSwitch('no-sandbox');
  app.commandLine.appendSwitch('disable-web-security');
  app.commandLine.appendSwitch('disable-features', 'TranslateUI');
  app.commandLine.appendSwitch('disable-ipc-flooding-protection');
  app.commandLine.appendSwitch('lang', 'zh-CN'); // 设置中文语言，解决乱码
  
  console.log('App initialized and command line switches set');
  
  // 创建窗口
  createWindow();
  
  // 延迟注册全局快捷键，确保应用完全启动
  setTimeout(() => {
    try {
      // 注册全局快捷键，用于退出应用
      const ret = globalShortcut.register('CommandOrControl+Alt+Q', () => {
        console.log('Exit shortcut pressed, quitting app');
        app.quit();
      });
      
      if (!ret) {
        console.error('Global shortcut registration failed, trying alternative');
        // 尝试其他组合键
        const altRet = globalShortcut.register('Alt+Q', () => {
          console.log('Alternative exit shortcut pressed, quitting app');
          app.quit();
        });
        
        if (!altRet) {
          console.error('Alternative shortcut also failed to register');
        } else {
          console.log('Registered alternative exit shortcut: Alt+Q');
        }
      } else {
        console.log('Registered exit shortcut: Ctrl+Alt+Q');
      }
    } catch (error) {
      console.error('Error registering global shortcut:', error);
    }
  }, 3000); // 延迟3秒注册快捷键
});

// 保持对window对象的全局引用，否则JS垃圾回收时窗口会自动关闭
let mainWindow;
let activePopups = [];
let isOnCooldown = false;
let isProcessingClipboard = false; // 添加标志，防止处理剪贴板时重复触发
let currentColorMode = 0;
let windowNeedsRecreation = false;
const COLOR_SCHEME_MODE = 4;
const COOLDOWN_TIME_MS = 500;

// 添加错误处理
process.on('uncaughtException', (error) => {
  console.error('未捕获的异常:', error);
});

process.on('unhandledRejection', (reason, promise) => {
  console.error('未处理的Promise拒绝:', reason);
});

function createWindow() {
  console.log('Creating window...');
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width: screenWidth, height: screenHeight } = primaryDisplay.workAreaSize;

  // 确保窗口完全在屏幕内可见
  const windowWidth = 222;
  const windowHeight = 222;
  // 确保窗口完全在屏幕内，距离屏幕边缘至少10像素
  const windowX = Math.max(10, screenWidth - windowWidth - 10);
  const windowY = Math.max(10, screenHeight - windowHeight - 10);
  console.log(`Screen resolution: ${screenWidth}x${screenHeight}, Window position: (${windowX}, ${windowY})`);

  // 创建浏览器窗口
  mainWindow = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: windowX,
    y: windowY,
    frame: false,             // 无边框
    transparent: false,       // 不透明背景，确保窗口可见
    alwaysOnTop: true,        // 窗口置顶
    skipTaskbar: true,        // 不在任务栏显示
    show: false,              // 初始不显示，防止闪烁
    resizable: false,
    webPreferences: {
      nodeIntegration: true,  // 允许在渲染进程中使用 Node.js API
      contextIsolation: false, // 为了简化，我们禁用上下文隔离
      enableRemoteModule: true,
      webSecurity: false,     // 禁用web安全限制，解决缓存问题
      allowRunningInsecureContent: true, // 允许运行不安全内容
      experimentalFeatures: true, // 启用实验性功能
      backgroundThrottling: false // 禁用后台节流，防止缓存错误
    }
  });

  // 加载 index.html
  mainWindow.loadFile('index.html').then(() => {
    console.log('Loaded index.html - success');
  }).catch(error => {
    console.error('Failed to load index.html:', error);
  });

  // 窗口事件监听
  mainWindow.on('show', () => {
    console.log('Window show event triggered');
    // 设置冷却，防止窗口显示时立即触发剪贴板检查
    setCooldown();
  });

  mainWindow.on('hide', () => {
    console.log('Window hide event triggered');
    // 设置冷却，防止窗口隐藏时立即触发剪贴板检查
    setCooldown();
  });

  mainWindow.on('blur', () => {
    console.log('Window blur event triggered');
    // 设置冷却，防止窗口失焦时立即触发剪贴板检查
    setCooldown();
  });

  mainWindow.on('focus', () => {
    console.log('Window focus event triggered');
    // 设置冷却，防止窗口聚焦时立即触发剪贴板检查
    setCooldown();
  });

  // 准备好显示时再显示窗口，防止白屏
  mainWindow.once('ready-to-show', () => {
    console.log('Window ready to show');
    // 不立即显示窗口，等待用户复制内容到剪贴板
    // mainWindow.show();
    // mainWindow.focus();
    console.log('Window created but hidden, waiting for clipboard content');
  });

  // 当窗口关闭时，将 window 对象解引用
  mainWindow.on('closed', () => {
    console.log('Window closed - event triggered');
    // 清空活动弹窗列表，但保留窗口重建逻辑
    activePopups = [];
    mainWindow = null;
    
    // 设置一个标志，表示需要重新创建窗口
    windowNeedsRecreation = true;
    console.log('Window closed, will recreate when clipboard changes');
    
    // 重置冷却状态，确保下次剪贴板变化能正常响应
    isOnCooldown = false;
  });
  
  // 当窗口隐藏时
  mainWindow.on('hide', () => {
    console.log('Window hide event triggered');
    // 不清空mainWindow，保持窗口对象引用
  });

  // 监听渲染进程关闭弹窗的请求
  ipcMain.on('close-popup', () => {
    console.log('Received close popup request');
    // 只有在非粘滞模式下且窗口可见时才关闭窗口
    const stickyPopups = activePopups.filter(p => p.isSticky);
    if (stickyPopups.length === 0 && mainWindow && mainWindow.isVisible()) {
      // 检查是否有正在滑出的弹窗
      const slidingOutPopup = activePopups.find(p => p.isSlidingOut);
      if (!slidingOutPopup) {
        // 只有在没有正在滑出的弹窗时才关闭窗口
        mainWindow.hide(); // 隐藏窗口
        // 设置标志，表示窗口已隐藏但对象仍然存在，确保能重新显示
        windowNeedsRecreation = false;
        console.log('Popup hidden, window object preserved for redisplay');
        
        // 清理活动弹窗列表，移除非粘滞模式的弹窗
        activePopups = activePopups.filter(p => p.isSticky);
        
        // 重置冷却状态，确保下次剪贴板变化能正常响应
        isOnCooldown = false;
        isProcessingClipboard = false; // 重置处理标志
      }
    }
  });

  // 监听用户主动关闭窗口的请求
  ipcMain.on('user-close-popup', () => {
    console.log('Received user close popup request');
    if (mainWindow && mainWindow.isVisible()) {
      mainWindow.close();
    }
  });

  // 监听渲染进程准备就绪的信号
  ipcMain.on('renderer-ready', () => {
    console.log('Renderer process ready');
    // 不在渲染进程准备就绪时立即显示剪贴板内容
    // onClipboardChanged();
  });

  // 监听手动检查剪贴板的请求
  ipcMain.on('check-clipboard', () => {
    console.log('Manual clipboard check');
    onClipboardChanged();
  });

  // 设置剪贴板监控
  setupClipboardMonitor(); // 重新启用剪贴板监控，但延迟到15秒后
  console.log('Window creation complete');
}

function setupClipboardMonitor() {
  let previousContent = null;
  let previousFormats = null;
  
  // 初始化时记录当前剪贴板内容，避免启动时触发
  try {
    previousContent = clipboard.readText();
    previousFormats = clipboard.availableFormats();
  } catch (error) {
    console.error('Failed to read initial clipboard content:', error);
    previousContent = '';
    previousFormats = [];
  }
  
  // 检查剪贴板变化
  function checkClipboard() {
    try {
      // 获取当前剪贴板内容和格式
      const currentContent = clipboard.readText();
      const currentFormats = clipboard.availableFormats();
      
      // 检查内容或格式是否有变化
      const contentChanged = currentContent !== previousContent;
      const formatsChanged = JSON.stringify(currentFormats) !== JSON.stringify(previousFormats);
      
      // 如果内容或格式有变化
      if ((contentChanged || formatsChanged) && (currentContent.trim() !== '' || currentFormats.length > 0)) {
        console.log('Detected clipboard content change');
        console.log('Current formats:', currentFormats);
        
        // 检查是否有图片内容
        const hasImage = currentFormats.includes('image/png') || currentFormats.includes('image/jpeg');
        
        if (hasImage) {
          // 如果有图片，直接调用onClipboardChanged，不传入文本数据
          onClipboardChanged();
        } else {
          // 如果没有图片，传入文本数据
          onClipboardChanged({
            text: currentContent
          });
        }
        
        previousContent = currentContent;
        previousFormats = currentFormats;
      }
    } catch (error) {
      console.error('Error checking clipboard:', error);
    }
  }
  
  // 延迟开始监控，确保应用完全启动
  setTimeout(() => {
    console.log('Starting clipboard monitoring');
    // 定期检查剪贴板变化，增加检查间隔以减少频繁触发
    setInterval(checkClipboard, 500);
  }, 15000); // 延迟到15秒后开始监控剪贴板，确保应用完全启动
}

function onClipboardChanged(clipboardData) {
  console.log('Checking clipboard changes...');
  if (isOnCooldown) return;
  
  // 防止在处理剪贴板时重复触发
  if (isProcessingClipboard) {
    console.log('Ignoring clipboard change - already processing');
    return;
  }

  // 设置处理标志
  isProcessingClipboard = true;

  try {
    // 如果窗口不存在或需要重新创建，创建新窗口
    if (!mainWindow || mainWindow.isDestroyed() || windowNeedsRecreation) {
      console.log('Window not available or needs recreation, creating new window');
      windowNeedsRecreation = true;
      createWindow();
      
      // 等待窗口创建完成后再处理剪贴板内容
      setTimeout(() => {
        isProcessingClipboard = false; // 重置标志
        onClipboardChanged(clipboardData);
      }, 1000);
      setCooldown();
      return;
    }

    // 检查是否有正在滑出的弹窗
    const slidingOutPopup = activePopups.find(p => p.isSlidingOut);
    if (slidingOutPopup) {
      isProcessingClipboard = false; // 重置标志
      setCooldown();
      return;
    }

    let data = null;

    // 如果传入了剪贴板数据，直接使用
    if (clipboardData && clipboardData.text) {
      data = {
        type: 'text',
        topText: clipboardData.text,
        bottomText: formatSize(Buffer.byteLength(clipboardData.text, 'utf8'))
      };
    } else {
      // 否则从剪贴板读取
      const formats = clipboard.availableFormats();

      // 处理文件/URL - 检查更多Windows剪贴板格式
      const hasFiles = formats.includes('text/uri-list') || 
                      formats.includes('text/plain') || 
                      formats.includes('Files') || 
                      formats.includes('FileNameW') || 
                      formats.includes('FileName') ||
                      formats.includes('FileGroupDescriptorW') ||
                      formats.includes('FileContents') ||
                      formats.includes('Preferred DropEffect');
      
      if (hasFiles) {
        let uris = [];
        
        // 尝试多种方式获取文件路径
        // 1. 尝试获取text/uri-list格式
        if (formats.includes('text/uri-list')) {
          try {
            const uriList = clipboard.read('text/uri-list');
            if (uriList) {
              uris = uriList.split('\n').filter(uri => uri.trim());
              console.log('Got file paths from text/uri-list:', uris);
            }
          } catch (e) {
            console.log('Failed to read text/uri-list:', e.message);
          }
        }
        
        // 2. 尝试获取text/plain格式（可能是文件路径）
        if (uris.length === 0 && formats.includes('text/plain')) {
          try {
            const plainText = clipboard.readText();
            if (plainText) {
              // 检查是否是文件路径
              if (plainText.includes('\\') || plainText.includes('/')) {
                uris = plainText.split('\n')
                  .filter(line => line.trim() !== '')
                  .map(line => line.trim());
                console.log('Got file paths from text/plain:', uris);
              }
            }
          } catch (e) {
            console.log('Failed to read text/plain:', e.message);
          }
        }
        
        // 3. 尝试获取Windows特定的文件格式
        if (uris.length === 0) {
          ['Files', 'FileNameW', 'FileName'].forEach(format => {
            if (formats.includes(format) && uris.length === 0) {
              try {
                const files = clipboard.read(format);
                if (files) {
                  // Windows可能返回的是文件路径的字符串表示
                  const paths = files.split('\n')
                    .filter(line => line.trim() !== '')
                    .map(line => line.trim());
                  if (paths.length > 0) {
                    uris = paths;
                    console.log(`Got file paths from ${format} format:`, uris);
                  }
                }
              } catch (e) {
                console.log(`Failed to read ${format} format:`, e.message);
              }
            }
          });
        }
        
        // 4. 尝试使用原生文件列表API（Electron提供）
        if (uris.length === 0 && formats.includes('text/plain')) {
          try {
            // 在Windows上，复制文件时剪贴板可能包含文件路径列表
            const plainText = clipboard.readText();
            if (plainText) {
              // 检查是否包含Windows文件路径特征
              const lines = plainText.split('\n').filter(line => line.trim());
              const filePaths = lines.filter(line => {
                // 检查是否是有效的Windows路径
                const trimmedLine = line.trim();
                return (trimmedLine.includes(':\\') || trimmedLine.startsWith('\\')) && 
                       !trimmedLine.includes('http') &&
                       !trimmedLine.includes('www.');
              });
              
              if (filePaths.length > 0) {
                uris = filePaths;
                console.log('Got file paths from Windows path detection:', uris);
              }
            }
          } catch (e) {
            console.log('Failed to detect Windows file paths:', e.message);
          }
        }
        
        // 5. 尝试处理特殊格式的文件路径（如立即的文件夹内容）
        if (uris.length === 0 && formats.includes('text/plain')) {
          try {
            const plainText = clipboard.readText();
            if (plainText) {
              // 检查是否是特殊格式的路径，如 "/e:/s/wol/py/kope/立即"
              const specialPathMatch = plainText.match(/^\/([a-zA-Z]):\/(.+)\/(.+)$/);
              if (specialPathMatch) {
                // 转换为Windows路径格式
                const drive = specialPathMatch[1];
                const path = specialPathMatch[2];
                const folderName = specialPathMatch[3];
                const windowsPath = `${drive}:\\${path.replace(/\//g, '\\')}\\${folderName}`;
                
                if (fs.existsSync(windowsPath)) {
                  uris = [windowsPath];
                  console.log('Converted special path format to Windows path:', uris);
                }
              }
            }
          } catch (e) {
            console.log('Failed to process special path format:', e.message);
          }
        }
        
        if (uris.length > 0) {
          data = processUris(uris);
        }
      }

      // 处理图片
      if (!data && formats.includes('image/png')) {
        const image = clipboard.readImage();
        if (!image.isEmpty()) {
          const size = image.getSize();
          data = {
            type: 'image',
            topText: `${size.width}×${size.height}`,
            bottomText: `截图: ${formatSize(image.toPNG().length)}`
          };
        }
      }

      // 处理文本
      if (!data && formats.includes('text/plain')) {
        const text = clipboard.readText();
        if (text) {
          data = {
            type: 'text',
            topText: text,
            bottomText: formatSize(Buffer.byteLength(text, 'utf8'))
          };
        }
      }

      // 处理其他格式
      if (!data && formats.length > 0) {
        const filteredFormats = formats.filter(f => 
          !f.startsWith('application/x-qt-') && 
          f !== 'text/plain' && 
          f !== 'text/uri-list'
        );
        
        if (filteredFormats.length > 0) {
          const primaryType = filteredFormats[0];
          try {
            const rawData = clipboard.read(primaryType);
            data = {
              type: 'other',
              topText: `未知内容，类型: ${primaryType}`,
              bottomText: formatSize(rawData ? rawData.length : 0)
            };
          } catch (e) {
            console.error('Failed to read clipboard data:', e);
          }
        }
      }
    }

    // 如果没有内容，不显示任何内容
    if (!data) {
      console.log('Clipboard is empty, not showing popup');
      isProcessingClipboard = false; // 重置标志
      setCooldown();
      return;
    }

    // 播放音效
    if (mainWindow && mainWindow.webContents) {
      mainWindow.webContents.send('play-sound', 'random');
    }

    // 检查是否有粘滞模式的弹窗
    const stickyPopups = activePopups.filter(p => p.isSticky);
    if (stickyPopups.length > 0) {
      isProcessingClipboard = false; // 重置标志
      setCooldown();
      return;
    }

    // 如果已经有非粘滞模式的弹窗，先关闭它
    const nonStickyPopup = activePopups.find(p => !p.isSticky);
    if (nonStickyPopup && !nonStickyPopup.isSlidingOut && mainWindow && mainWindow.isVisible()) {
      console.log('Closing existing popup');
      // 标记为正在滑出
      nonStickyPopup.isSlidingOut = true;
      if (mainWindow && mainWindow.webContents) {
        mainWindow.webContents.send('close-popup');
      }
      // 不立即返回，等待关闭动画完成后再显示新内容
      setTimeout(() => {
        isProcessingClipboard = false; // 重置标志
        showNewPopup(data);
      }, 350); // 等待关闭动画完成
      setCooldown();
      return;
    }

    // 如果没有现有弹窗，直接显示新内容
    isProcessingClipboard = false; // 重置标志
    showNewPopup(data);
    setCooldown();
  } catch (error) {
    console.error('Error handling clipboard change:', error);
    isProcessingClipboard = false; // 重置标志
  }
}

function showNewPopup(data) {
  // 播放音效
  if (mainWindow && mainWindow.webContents) {
    mainWindow.webContents.send('play-sound', 'random');
  }

  // 如果窗口不存在或需要重新创建，创建新窗口
  if (!mainWindow || mainWindow.isDestroyed() || windowNeedsRecreation) {
    console.log('Window not available or needs recreation, creating new window');
    windowNeedsRecreation = true;
    createWindow();
    
    // 等待窗口创建完成后再显示内容
    setTimeout(() => {
      if (mainWindow && mainWindow.webContents && !mainWindow.isDestroyed()) {
        showPopupContent(data);
      } else {
        // 如果窗口仍然不可用，再次尝试
        console.log('Window still not ready, retrying...');
        setTimeout(() => {
          if (mainWindow && mainWindow.webContents && !mainWindow.isDestroyed()) {
            showPopupContent(data);
          } else {
            console.error('Failed to create window for popup');
          }
        }, 1000);
      }
    }, 1000);
    return;
  }
  
  // 如果窗口存在但已隐藏，直接显示内容
  if (mainWindow && !mainWindow.isVisible()) {
    console.log('Window exists but hidden, showing content');
    showPopupContent(data);
    return;
  }
  
  // 如果窗口存在且可见，先关闭当前弹窗再显示新内容
  if (mainWindow && mainWindow.isVisible()) {
    console.log('Window exists and visible, closing current popup first');
    // 标记为正在滑出
    const nonStickyPopup = activePopups.find(p => !p.isSticky);
    if (nonStickyPopup) {
      nonStickyPopup.isSlidingOut = true;
    }
    
    if (mainWindow.webContents) {
      mainWindow.webContents.send('close-popup');
    }
    
    // 等待关闭动画完成后再显示新内容
    setTimeout(() => {
      if (mainWindow && mainWindow.webContents && !mainWindow.isDestroyed()) {
        showPopupContent(data);
      } else {
        // 如果窗口在等待期间被销毁，重新创建
        console.log('Window destroyed during wait, recreating');
        windowNeedsRecreation = true;
        showNewPopup(data);
      }
    }, 350);
    return;
  }
  
  // 默认情况，直接显示内容
  showPopupContent(data);
}

function showPopupContent(data) {
  // 更新颜色模式
  if (COLOR_SCHEME_MODE === 3 || COLOR_SCHEME_MODE === 4) {
    currentColorMode = 1 - currentColorMode;
  } else if (COLOR_SCHEME_MODE === 2) {
    currentColorMode = 1;
  } else {
    currentColorMode = 0;
  }

  // 创建新弹窗
  if (mainWindow && mainWindow.webContents) {
      console.log('Preparing to show window, sending content update');
      mainWindow.webContents.send('update-popup-content', {
          topText: data.topText || '',
          bottomText: data.bottomText || ''
      });
      
      // 发送颜色模式
      mainWindow.webContents.send('update-color-mode', currentColorMode);
      
      // 如果窗口被隐藏，先显示窗口
      if (!mainWindow.isVisible()) {
        mainWindow.show();
        console.log('Window shown before displaying content');
      }
      
      // 显示窗口
      console.log('Showing window at position:', mainWindow.getPosition());
      mainWindow.focus();
      mainWindow.setAlwaysOnTop(true, 'screen-saver'); // 确保窗口始终在最顶层
      
      // 延迟设置焦点，确保窗口完全显示后再获得焦点
      setTimeout(() => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.focus();
          console.log('Delayed window focus setting');
        }
      }, 100);
      
      // 更新活动弹窗列表，先过滤掉已滑出的弹窗
      activePopups = activePopups.filter(p => !p.isSlidingOut);
      activePopups.push({
          isSticky: false,
          isSlidingOut: false
      });
      
      console.log('Window shown and focused');
  } else {
        console.error('Cannot show window: mainWindow or webContents not available');
    }
  
  // 如果是文件类型，异步计算大小
  if (data.type === 'file' && data.paths) {
    calculateTotalSizeAsync(data.paths, data.bottomTemplate);
  }
}

function processUris(uris) {
  const localPaths = [];
  const remoteUrls = [];

  uris.forEach(uri => {
    // 处理Windows路径
    if (uri.startsWith('file:///')) {
      const path = uri.replace(/^file:\/\/\//, '').replace(/\//g, '\\');
      if (fs.existsSync(path)) {
        localPaths.push(path);
      }
    } else if (uri.startsWith('http://') || uri.startsWith('https://')) {
      remoteUrls.push(uri);
    } else if (uri.includes('\\') || (uri.includes('/') && !uri.startsWith('http'))) {
      // 处理直接的Windows路径或Unix路径
      // 清理路径，移除可能的引号
      const cleanPath = uri.replace(/^["']|["']$/g, '').trim();
      if (fs.existsSync(cleanPath)) {
        localPaths.push(cleanPath);
      }
    }
  });

  // 优先处理本地路径
  if (localPaths.length > 0) {
    const fileCount = localPaths.filter(p => {
      try {
        return fs.statSync(p).isFile();
      } catch (e) {
        return false;
      }
    }).length;
    
    const folderCount = localPaths.filter(p => {
      try {
        return fs.statSync(p).isDirectory();
      } catch (e) {
        return false;
      }
    }).length;
    
    let topText = localPaths.map(p => path.basename(p)).join('\n');
    let bottomTemplate;
    
    if (localPaths.length === 1) {
      bottomTemplate = folderCount === 1 ? '文件夹: {}' : '文件: {}';
    } else {
      if (fileCount > 0 && folderCount > 0) {
        bottomTemplate = `${localPaths.length} 个项目: {}`;
      } else if (folderCount > 0) {
        bottomTemplate = `${localPaths.length} 个文件夹: {}`;
      } else {
        bottomTemplate = `${localPaths.length} 个文件: {}`;
      }
    }

    return {
      type: 'file',
      topText,
      bottomTemplate,
      paths: localPaths
    };
  } else if (remoteUrls.length > 0) {
    return {
      type: 'other',
      topText: `复制了 ${remoteUrls.length} 个 URL`,
      bottomText: remoteUrls[0].substring(0, 50) + (remoteUrls[0].length > 50 ? '...' : '')
    };
  }

  return null;
}

function calculateTotalSizeAsync(paths, template) {
  if (!mainWindow || !mainWindow.webContents) return;
  
  // 在Node.js环境中计算总大小
  let totalSize = 0;
  
  try {
    paths.forEach(path => {
      try {
        const stats = fs.statSync(path);
        if (stats.isDirectory()) {
          // 简单计算目录大小（不递归）
          const files = fs.readdirSync(path);
          files.forEach(file => {
            try {
              const filePath = path.join(path, file);
              const fileStats = fs.statSync(filePath);
              if (fileStats.isFile()) {
                totalSize += fileStats.size;
              }
            } catch (e) {
              // 忽略无法访问的文件
            }
          });
        } else {
          totalSize += stats.size;
        }
      } catch (e) {
        // 忽略无法访问的路径
      }
    });
  } catch (error) {
    console.error('Failed to calculate file size:', error);
  }

  // 发送结果到渲染进程
  mainWindow.webContents.send('update-bottom-text', template.replace('{}', formatSize(totalSize)));
}

function formatSize(sizeBytes) {
  if (sizeBytes === undefined || sizeBytes === null) return 'N/A';
  
  if (sizeBytes < 1024) return `${Math.round(sizeBytes)} b`;
  
  const kb = sizeBytes / 1024;
  if (kb < 1024) return `${Math.round(kb)} K`;
  
  const mb = kb / 1024;
  return `${Math.round(mb)} M`;
}

function setCooldown() {
  isOnCooldown = true;
  setTimeout(() => {
    isOnCooldown = false;
  }, COOLDOWN_TIME_MS);
}



// 应用即将退出时，取消注册所有快捷键
app.on('will-quit', () => {
  console.log('App about to quit, unregistering all shortcuts');
  globalShortcut.unregisterAll();
});

// 当所有窗口关闭时退出应用
app.on('window-all-closed', () => {
  console.log('All windows closed - event triggered');
  // 在 macOS 上，除非用户用 Cmd + Q 确定退出，
  // 否则应用及其菜单栏会保持活动状态。
  // 注释掉自动退出逻辑，让应用持续运行监控剪贴板
  /*
  if (process.platform !== 'darwin') {
    console.log('Non-macOS platform, quitting app');
    app.quit();
  } else {
    console.log('macOS platform, not quitting app');
  }
  */
  console.log('Keeping app running, continuing clipboard monitoring');
});

app.on('activate', () => {
  console.log('App activated');
  // 在 macOS 上，当单击 dock 图标并且没有其他窗口打开时，
  // 通常在应用程序中重新创建一个窗口。
  if (mainWindow === null) {
    createWindow();
  }
});

// 应用即将退出
app.on('before-quit', () => {
  console.log('App about to quit');
});