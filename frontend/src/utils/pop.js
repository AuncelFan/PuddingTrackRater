// 通用弹窗
export function showPop(message) {
    // 创建弹窗容器
    const popContainer = document.createElement('div');
    popContainer.className = 'pop-container';
    popContainer.innerHTML = `<div class='pop-message'>${message}</div>`;

    // 添加到页面
    document.body.appendChild(popContainer);
    popContainer.classList.add('show');
    // 3秒后自动移除
    setTimeout(() => {
        popContainer.classList.remove('show');
        setTimeout(() => {
            document.body.removeChild(popContainer);
        }, 300);
    }, 2000);
}