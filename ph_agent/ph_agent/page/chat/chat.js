frappe.pages["chat"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "AI Chat",
		single_column: true,
	});

	$(wrapper).html(`
		<div id="ph-chat-root" style="height: calc(100vh - 60px); display: flex; align-items: center; justify-content: center;">
			<div style="text-align: center; color: #6c757d;">
				<div style="font-size: 48px; margin-bottom: 16px;">💬</div>
				<h3>AI Chat</h3>
				<p>Chat page loaded successfully. Full UI coming in next step.</p>
			</div>
		</div>
	`);
};
