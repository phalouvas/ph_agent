/**
 * PH Agent - Tool Approval Request
 * 
 * Desk UI for approving/rejecting tool requests.
 * Provides list view buttons and form actions for the approval workflow.
 */

frappe.ui.form.on("Tool Approval Request", {
	refresh: function (frm) {
		// Only show action buttons for pending requests
		if (frm.doc.status !== "Pending") {
			return;
		}

		// Approve button
		frm.add_custom_button(
			__("Approve"),
			function () {
				frappe.confirm(
					__("Are you sure you want to approve the execution of tool '{0}'?", [
						frm.doc.tool_name,
					]),
					function () {
						frm.call({
							method: "approve",
							doc: frm.doc,
							callback: function (r) {
								if (r.message && r.message.status === "ok") {
									frappe.msgprint(
										__("Tool '{0}' approved. Execution has been enqueued.", [
											frm.doc.tool_name,
										])
									);
									frm.refresh();
								}
							},
							error: function (err) {
								frappe.msgprint({
									title: __("Approval Failed"),
									indicator: "red",
									message: err.message,
								});
							},
						});
					}
				);
			}
		).addClass("btn-primary");

		// Reject button
		frm.add_custom_button(
			__("Reject"),
			function () {
				const d = new frappe.ui.Dialog({
					title: __("Reject Tool Request"),
					fields: [
						{
							fieldname: "reason",
							fieldtype: "Small Text",
							label: __("Reason for Rejection"),
							reqd: 1,
							description: __(
								"This reason will be shown to the user in the chat."
							),
						},
					],
					primary_action_label: __("Reject"),
					primary_action: function () {
						const values = d.get_values();
						if (!values) return;

						frm.call({
							method: "reject",
							doc: frm.doc,
							args: {
								reason: values.reason,
							},
							callback: function (r) {
								if (r.message && r.message.status === "ok") {
									frappe.msgprint(
										__("Tool '{0}' has been rejected.", [
											frm.doc.tool_name,
										])
									);
									d.hide();
									frm.refresh();
								}
							},
							error: function (err) {
								frappe.msgprint({
									title: __("Rejection Failed"),
									indicator: "red",
									message: err.message,
								});
							},
						});
					},
				});
				d.show();
			}
		).addClass("btn-danger");
	},
});

// List view: Add Approve/Reject bulk actions
frappe.listview_settings["Tool Approval Request"] = {
	add_fields: ["status", "tool_name", "chat_session"],
	has_indicator_for_draft: false,
	get_indicator: function (doc) {
		const status_colors = {
			Pending: "orange",
			Approved: "green",
			Rejected: "red",
			Cancelled: "gray",
		};
		return [__(doc.status), status_colors[doc.status] || "gray"];
	},
	button: {
		show: function (doc) {
			return doc.status === "Pending";
		},
		get_label: function () {
			return __("Review");
		},
		get_description: function (doc) {
			return __("Review {0}", [doc.tool_name]);
		},
		action: function (doc) {
			frappe.set_route("Form", "Tool Approval Request", doc.name);
		},
	},
};
